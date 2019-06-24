# SPDX-License-Identifier: BSD-3-Clause
# Copyright(c) 2018 Nippon Telegraph and Telephone Corporation

from .. import spp_common
from ..shell_lib import common
from ..spp_common import logger
import time


class SppPrimary(object):
    """Exec SPP primary command.

    SppPrimary class is intended to be used in Shell class as a delegator
    for running 'pri' command.

    'self.run()' is called from do_pri() and 'self.complete()' is called
    from complete_pri() of both of which is defined in Shell.
    """

    # All of primary commands used for validation and completion.
    PRI_CMDS = ['status', 'launch', 'clear']

    def __init__(self, spp_ctl_cli):
        self.spp_ctl_cli = spp_ctl_cli

        # Default args for `pri; launch`, used if given cli_config is invalid

        # TODO(yasufum) replace placeholders __XXX__ to {keyword}.
        # Setup template of args for `pri; launch`
        temp = "-l __MASTER_LCORE__,{slcores} "
        temp = temp + "__MEM__ "
        temp = temp + "-- "
        temp = temp + "{opt_sid} {sid} "  # '-n 1' or '--client-id 1'
        temp = temp + "-s {sec_addr} "  # '-s 192.168.1.100:6666'
        temp = temp + "__VHOST_CLI__"
        self.launch_template = temp

    def run(self, cmd, cli_config):
        """Called from do_pri() to Send command to primary process."""

        tmpary = cmd.split(' ')
        subcmd = tmpary[0]
        params = tmpary[1:]

        if not (subcmd in self.PRI_CMDS):
            print("Invalid pri command: '{}'".format(subcmd))
            return None

        # use short name
        common_err_codes = self.spp_ctl_cli.rest_common_error_codes

        if subcmd == 'status':
            res = self.spp_ctl_cli.get('primary/status')
            if res is not None:
                if res.status_code == 200:
                    self.print_status(res.json())
                elif res.status_code in common_err_codes:
                    # Print default error message
                    pass
                else:
                    print('Error: unknown response.')

        elif subcmd == 'launch':
            wait_time = float(cli_config['sec_wait_launch']['val'])
            self._run_launch(params, wait_time)

        elif subcmd == 'clear':
            res = self.spp_ctl_cli.delete('primary/status')
            if res is not None:
                if res.status_code == 204:
                    print('Clear port statistics.')
                elif res.status_code in common_err_codes:
                    pass
                else:
                    print('Error: unknown response.')

        else:
            print('Invalid pri command!')

    def do_exit(self):
        res = self.spp_ctl_cli.delete('primary')

        if res is not None:
            error_codes = self.spp_ctl_cli.rest_common_error_codes
            if res.status_code == 204:
                print('Exit primary')
            elif res.status_code in error_codes:
                pass
            else:
                print('Error: unknown response.')

    def print_status(self, json_obj):
        """Parse SPP primary's status and print.

        Primary returns the status as JSON format, but it is just a little
        long.

            {
                "lcores": [0, 3],
                "phy_ports": [
                    {
                        "eth": "56:48:4f:12:34:00",
                        "id": 0,
                        "rx": 78932932,
                        "tx": 78932931,
                        "tx_drop": 1,
                    }
                    ...
                ],
                "ring_ports": [
                    {
                        "id": 0,
                        "rx": 89283,
                        "rx_drop": 0,
                        "tx": 89283,
                        "tx_drop": 0
                    },
                    ...
                ]
            }

        It is formatted to be simple and more understandable.

            - lcores:
                [0, 3]
            - physical ports:
                ID          rx          tx     tx_drop  mac_addr
                 0    78932932    78932931           1  56:48:4f:53:54:00
            - ring ports:
                ID          rx          tx     rx_drop     tx_drop
                 0       89283       89283           0           0
                 ...
        """

        if 'lcores' in json_obj:
            print('- lcores:')
            print('  - {}'.format(json_obj['lcores']))

        if 'phy_ports' in json_obj:
            print('- physical ports:')
            print('    ID          rx          tx     tx_drop  mac_addr')

            temp = '    {portid:2}  {rx:10}  {tx:10}  {tx_drop:10}  {eth}'
            for pports in json_obj['phy_ports']:
                print(temp.format(
                    portid=pports['id'], rx=pports['rx'], tx=pports['tx'],
                    tx_drop=pports['tx_drop'], eth=pports['eth']))

        if 'ring_ports' in json_obj:
            print('- ring ports:')
            print('    ID          rx          tx     rx_drop     tx_drop')
            temp = '    {rid:2}  {rx:10}  {tx:10}  {rx_drop:10}  {tx_drop:10}'
            for rports in json_obj['ring_ports']:
                print(temp.format(
                    rid=rports['id'], rx=rports['rx'], tx=rports['tx'],
                    rx_drop=rports['rx_drop'], tx_drop=rports['tx_drop']))

    def _get_empty_lcores(self):
        """Get lcore usage from spp-ctl for making launch options.

        Return value is a double dimension list of unsed lcores.
          [[2,3,...], [16,17,...]]

        To get the result, get CPU layout as an list first, then remove
        used lcores from the list.
        """

        sockets = []  # A set of CPU sockets.
        # Get list of CPU layout
        res = self.spp_ctl_cli.get('cpu_layout')
        if res is not None:
            if res.status_code == 200:
                try:
                    # Get layout of each of sockets as an array.
                    # [[0,1,2,3,..., 15], [16,17,18],...]]
                    socket = []
                    for sock in res.json():
                        for ent in sock['cores']:
                            socket.append(ent['lcores'])
                    socket.sort()
                    socket = sum(socket, [])
                    sockets.append(socket)

                except KeyError as e:
                    print('Error: {} is not defined!'.format(e))

        # Get list of used lcores.
        res = self.spp_ctl_cli.get('cpu_usage')
        if res is not None:
            if res.status_code == 200:
                try:
                    p_master_lcore = None
                    s_master_lcore = None
                    p_slave_lcores = []
                    s_slave_lcores = []

                    cpu_usage = res.json()
                    for ent in cpu_usage:
                        if ent['proc-type'] == 'primary':
                            p_master_lcore = ent['master-lcore']
                            p_slave_lcores.append(ent['lcores'])
                        else:
                            s_master_lcore = ent['master-lcore']
                            s_slave_lcores.append(ent['lcores'])

                    # Remove duplicated lcores and make them unique.
                    # sum() is used for flattening two dimension list.
                    p_slave_lcores = list(set(sum(p_slave_lcores, [])))
                    s_slave_lcores = list(set(sum(s_slave_lcores, [])))

                    # Remove used lcores from `sockets`.
                    for socket in sockets:
                        if p_master_lcore is not None:
                            if p_master_lcore in socket:
                                socket.remove(p_master_lcore)
                        if s_master_lcore is not None:
                            if s_master_lcore in socket:
                                socket.remove(s_master_lcore)
                        for l in p_slave_lcores:
                            if l in socket:
                                socket.remove(l)
                        for l in s_slave_lcores:
                            if l in socket:
                                socket.remove(l)

                except KeyError as e:
                    print('Error: {} is not defined!'.format(e))

        return sockets

    def _setup_launch_opts(self, tokens, cli_config):
        """Make options for launch cmd from config params."""

        if 'max_secondary' in cli_config.keys():
            max_secondary = int(cli_config['max_secondary']['val'])

            if (tokens[2] in spp_common.SEC_TYPES) and \
                    (int(tokens[3])-1 in range(max_secondary)):
                ptype = tokens[2]

                # TODO(yasufum) Not accept if given sec ID is already
                # used.
                sid = tokens[3]

                # Option of secondary ID is different between spp_nfv
                # and others.
                if ptype == 'nfv':
                    opt_sid = '-n'
                else:
                    opt_sid = '--client-id'

                # Need to replace port from `7777` of spp-ctl to `6666`
                # of secondary process.
                server_addr = common.current_server_addr()
                server_addr = server_addr.replace('7777', '6666')

                # Define number of slave lcores and other options
                # from config.
                if ptype == 'nfv':  # one slave lcore is enough
                    if 'sec_nfv_nof_lcores' in cli_config.keys():
                        tmpkey = 'sec_nfv_nof_lcores'
                        nof_slaves = int(
                                cli_config[tmpkey]['val'])
                elif ptype == 'vf':
                    if 'sec_vf_nof_lcores' in cli_config.keys():
                        nof_slaves = int(
                                cli_config['sec_vf_nof_lcores']['val'])
                elif ptype == 'mirror':  # two slave lcores
                    if 'sec_mirror_nof_lcores' in cli_config.keys():
                        tmpkey = 'sec_mirror_nof_lcores'
                        nof_slaves = int(
                                cli_config[tmpkey]['val'])
                elif ptype == 'pcap':  # at least two slave lcores
                    if 'sec_pcap_nof_lcores' in cli_config.keys():
                        tmpkey = 'sec_pcap_nof_lcores'
                        nof_slaves = int(
                                cli_config[tmpkey]['val'])
                    if 'sec_pcap_port' in cli_config.keys():
                        temp = '-c {}'.format(
                                cli_config['sec_pcap_port']['val'])

                        self.launch_template = '{} {}'.format(
                            self.launch_template, temp)

                # Get and flatten empty lcores on each of sockets.
                empty_lcores = self._get_empty_lcores()
                empty_lcores = sum(empty_lcores, [])

                if 'sec_m_lcore' in cli_config.keys():
                    m_lcore_id = int(cli_config['sec_m_lcore']['val'])

                # Decide lcore option based on configured number of
                # lcores.
                slave_lcores = []
                for l in empty_lcores:
                    # Master lcore ID should be smaller than slaves.
                    if l > m_lcore_id:
                        slave_lcores.append(str(l))
                    # TODO(yasufum) warn if enough number of empty
                    # lcores cannot be assinged.
                    if len(slave_lcores) > (nof_slaves - 1):
                        break

                # TODO(yasufum) make smarter form, for example,
                # change '1,2,3' to '1-3'.
                slave_lcores = ','.join(slave_lcores)

                # Replace labels in template with actual params to make
                # candidate options.
                temp = self._setup_launch_template(
                        cli_config, self.launch_template)
                candidates = [temp.format(
                    slcores=slave_lcores, opt_sid=opt_sid, sid=sid,
                    sec_addr=server_addr)]

        else:
            logger.error(
                    'Error: max_secondary is not defined in config')
            candidates = []

        return candidates

    # TODO(yasufum) add checking for cli_config has keys
    def complete(self, text, line, begidx, endidx, cli_config):
        """Completion for primary process commands.

        Called from complete_pri() to complete primary command.
        """

        candidates = []
        tokens = line.split(' ')

        # Parse command line
        if tokens[0].endswith(';'):

            # Show sub commands
            if len(tokens) == 2:
                # Add sub commands
                candidates = candidates + self.PRI_CMDS[:]

            # Show args of `launch` sub command.
            elif len(tokens) == 3 and tokens[1] == 'launch':
                for pt in spp_common.SEC_TYPES:
                    candidates.append('{}'.format(pt))

            elif len(tokens) == 4 and tokens[1] == 'launch':
                if 'max_secondary' in cli_config.keys():
                    max_secondary = int(cli_config['max_secondary']['val'])

                    if tokens[2] in spp_common.SEC_TYPES:
                        candidates = [
                                str(i+1) for i in range(max_secondary)]
                else:
                    logger.error(
                            'Error: max_secondary is not defined in config')
                    candidates = []

            elif len(tokens) == 5 and tokens[1] == 'launch':
                candidates = self._setup_launch_opts(tokens, cli_config)

        if not text:
            completions = candidates
        else:
            completions = [p for p in candidates
                           if p.startswith(text)
                           ]

        return completions

    # TODO(yasufum) add checking for cli_config has keys
    def _setup_launch_template(self, cli_config, template):
        """Check given `cli_config` for params of launch."""

        if 'sec_mem' in cli_config.keys():
            sec_mem = cli_config['sec_mem']['val']
        template = template.replace('__MEM__', sec_mem)

        if 'sec_m_lcore' in cli_config.keys():
            sec_m_lcore = cli_config['sec_m_lcore']['val']
        template = template.replace('__MASTER_LCORE__', str(sec_m_lcore))

        if 'sec_vhost_cli' in cli_config.keys():
            if cli_config['sec_vhost_cli']['val']:
                vhost_client = '--vhost-client'
            else:
                vhost_client = ''
        template = template.replace('__VHOST_CLI__', vhost_client)

        return template

    def _get_sec_ids(self):
        sec_ids = []
        res = self.spp_ctl_cli.get('processes')
        if res is not None:
            if res.status_code == 200:
                try:
                    for proc in res.json():
                        if proc['type'] != 'primary':
                            sec_ids.append(proc['client-id'])
                except KeyError as e:
                    print('Error: {} is not defined!'.format(e))
            elif res.status_code in self.spp_ctl_cli.rest_common_error_codes:
                # Print default error message
                pass
            else:
                print('Error: unknown response.')
        return sec_ids

    def _setup_opts_dict(self, opts_list):
        """Setup options for sending to spp-ctl as a request body.

        Options is setup from given list. If option has no value, None is
        assgined for the value. For example,
          ['-l', '1-2', --no-pci, '-m', '512', ...]
          => {'-l':'1-2', '--no-pci':None, '-m':'512', ...}
        """
        prekey = None
        opts_dict = {}
        for opt in opts_list:
            if opt.startswith('-'):
                opts_dict[opt] = None
                prekey = opt
            else:
                if prekey is not None:
                    opts_dict[prekey] = opt
                    prekey = None
        return opts_dict

    def _run_launch(self, params, wait_time):
        """Launch secondary process.

        Parse `launch` command and send request to spp-ctl. Params of the
        consists of proc type, sec ID and arguments. It allows to skip some
        params which are completed. All of examples here are same.

        spp > lanuch nfv -l 1-2 ... -- -n 1 ...  # sec ID '1' is skipped
        spp > lanuch spp_nfv -l 1-2 ... -- -n 1 ...  # use 'spp_nfv' insteads
        """

        # Check params
        if len(params) < 2:
            print('Invalid syntax! Proc type, ID and options are required.')
            print('E.g. "nfv 1 -l 1-2 -m 512 -- -n 1 -s 192.168.1.100:6666"')
            return None

        proc_type = params[0]
        if params[1].startswith('-'):
            sec_id = None  # should be found later, or failed
            args = params[1:]
        else:
            sec_id = params[1]
            args = params[2:]

        if proc_type.startswith('spp_') is not True:
            proc_name = 'spp_' + proc_type
        else:
            proc_name = proc_type
            proc_type = proc_name[len('spp_'):]

        if proc_type not in spp_common.SEC_TYPES:
            print("'{}' is not supported in launch cmd.".format(proc_type))
            return None

        if '--' not in args:
            print('Arguments should include separator "--".')
            return None

        # Setup options of JSON sent to spp-ctl. Here is an example for
        # launching spp_nfv.
        #   {
        #      'client_id': '1',
        #      'proc_name': 'spp_nfv',
        #      'eal': {'-l': '1-2', '-m': '1024', ...},
        #      'app': {'-n': '1', '-s': '192.168.1.100:6666'}
        #   }
        idx_separator = args.index('--')
        eal_opts = args[:idx_separator]
        app_opts = args[(idx_separator+1):]

        if '--proc-type' not in args:
            eal_opts.append('--proc-type')
            eal_opts.append('secondary')

        opts = {'proc_name': proc_name}
        opts['eal'] = self._setup_opts_dict(eal_opts)
        opts['app'] = self._setup_opts_dict(app_opts)

        # Try to find sec_id from app options.
        if sec_id is None:
            if (proc_type == 'nfv') and ('-n' in opts['app']):
                sec_id = opts['app']['-n']
            elif ('--client-id' in opts['app']):  # vf, mirror or pcap
                sec_id = opts['app']['--client-id']
            else:
                print('Secondary ID is required!')
                return None

        if sec_id in self._get_sec_ids():
            print("Cannot add '{}' already used.".format(sec_id))
            return None

        opts['client_id'] = sec_id

        # Complete or correct sec_id.
        if proc_name == 'spp_nfv':
            if '-n' in opts['app'].keys():
                if (opts['app']['-n'] != sec_id):
                    opts['app']['-n'] = sec_id
            else:
                opts['app']['-n'] = sec_id
        else:  # vf, mirror or pcap
            if '--client-id' in opts['app'].keys():
                if (opts['app']['--client-id'] != sec_id):
                    opts['app']['--client-id'] = sec_id
            else:
                opts['app']['--client-id'] = sec_id

        logger.debug('launch, {}'.format(opts))

        # Send request for launch secondary.
        res = self.spp_ctl_cli.put('primary/launch', opts)
        if res is not None:
            error_codes = self.spp_ctl_cli.rest_common_error_codes
            if res.status_code == 204:
                # Wait for launch secondary as best effort
                time.sleep(wait_time)

                print('Send request to launch {ptype}:{sid}.'.format(
                    ptype=proc_type, sid=sec_id))
            elif res.status_code in error_codes:
                pass
            else:
                print('Error: unknown response.')

    @classmethod
    def help(cls):
        msg = """Send a command to primary process.

        Show resources and statistics, or clear it.
            spp > pri; status  # show status
            spp > pri; clear   # clear statistics

        Launch secondary process..
            # Launch nfv:1
            spp > pri; launch nfv 1 -l 1,2 -m 512 -- -n 1 -s 192.168....
            # Launch vf:2
            spp > pri; launch vf 2 -l 1,4-7 -m 512 -- --client-id 2 -s ...
        """

        print(msg)
