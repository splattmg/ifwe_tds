'''
Command and view resolver for TDS.
'''
import getpass
import os
import pwd
import logging

import tds.authorize
import tds.commands
import tds.views
import tds.utils

import tagopsdb
from tds.exceptions import AccessError, ConfigurationError
from tds.model import LocalActor


log = logging.getLogger('tds.main')


class TDS(object):
    """TDS main class"""

    _config = None
    _dbconfig = None

    view = tds.views.CLI

    command_map = {
        ('repository', 'list'): 'exec_repository_list',
    }

    def __init__(self, params):
        """Basic initialization"""

        self.params = params
        self.params['deployment'] = True

    @property
    def config(self):
        if self._config is None:
            self._config = self._load_config(self.params)
        return self._config

    @property
    def dbconfig(self):
        if self._dbconfig is None:
            self._dbconfig = self._load_dbconfig(self.params)
        return self._dbconfig

    @staticmethod
    def _load_config(*_args):
        'Load app config'
        config = tds.utils.config.TDSDeployConfig()
        config.load()

        return config

    @staticmethod
    def _load_dbconfig(params):
        'Load database config'
        dbconfig = tds.utils.config.TDSDatabaseConfig(
            params.get('user_level', 'dev')
        )
        dbconfig.load()

        return dbconfig

    @tds.utils.debug
    def check_user_auth(self):
        """Verify the user is authorized to run the application"""

        log.debug('Checking user authorization level')

        self.params['user_level'] = \
            tds.authorize.get_access_level(LocalActor())
        log.log(5, 'User level is: %s', self.params['user_level'])

        if self.params['user_level'] is None:
            raise AccessError('Your account (%s) is not allowed to run this '
                              'application.\nPlease refer to your manager '
                              'for assistance.' % self.params['user'])

    @tds.utils.debug
    def check_exclusive_options(self):
        """Ensure certain options are exclusive and set parameter
           to check for explicit hosts or application types
        """

        log.debug('Checking certain options are exclusive')

        # Slight hack: ensure only one of '--hosts', '--apptypes'
        # or '--all-apptypes' is used at a given time
        excl = filter(None, (self.params.get('hosts', None),
                             self.params.get('apptypes', None),
                             self.params.get('all_apptypes', None)))

        if len(excl) > 1:
            raise ConfigurationError('Only one of the "--hosts", '
                                     '"--apptypes" or "--all-apptypes" '
                                     'options may be used at a given time')

        if not excl:
            self.params['explicit'] = False
        else:
            self.params['explicit'] = True

        log.log(5, '"explicit" parameter is: %(explicit)s', self.params)

    @tds.utils.debug
    def update_program_parameters(self):
        """Set some additional program parameters"""

        log.debug('Adding several additional parameters for program')

        self.params['user'] = pwd.getpwuid(os.getuid()).pw_name
        log.log(5, 'User is: %s', self.params['user'])
        self.check_user_auth()

        self.params['environment'] = self.config['env.environment']
        log.log(5, 'Environment is: %s', self.params['environment'])

        self.params['repo'] = self.config['repo']

        log.log(5, '"repo" parameter values are: %r', self.params['repo'])

    @tds.utils.debug
    def initialize_db(self):
        """Get user/password information for the database and connect
           to the database
        """

        log.debug('Connecting to the database')

        if self.params.get('dbuser', None):
            db_user = self.params['dbuser']
            db_password = getpass.getpass('Enter DB password: ')
        else:
            db_user = self.dbconfig['db.user']
            db_password = self.dbconfig['db.password']

        tagopsdb.init(
            url=dict(
                username=db_user,
                password=db_password,
                host=self.dbconfig['db.hostname'],
                database=self.dbconfig['db.db_name'],
            ),
            pool_recycle=3600
        )

    @tds.utils.debug
    def execute_command(self):
        """Run the requested command for TDS"""

        log.debug('Running the requested command')
        command = (self.params['command_name'], self.params['subcommand_name'])
        handler_name = self.command_map.get(command, None)
        if handler_name is None:
            handler_name = 'exec_command_default'
        handler = getattr(self, handler_name, None)

        if handler is None:
            self.exec_command_default()
        else:
            handler()

    def exec_command_default(self):

        log.log(5, 'Instantiating class %r',
                self.params['command_name'].capitalize())

        cmd = getattr(tds.commands,
                      self.params['command_name'].capitalize())(log)

        try:
            log.log(5, 'Executing subcommand %r',
                    self.params['subcommand_name'].replace('-', '_'))
            getattr(
                cmd,
                self.params['subcommand_name'].replace('-', '_')
            )(self.params)
        except:
            raise   # Just pass error up to top level

    def exec_repository_list(self):
        tds.authorize.verify_access(self.params.get('user_level', 'disabled'), 'dev')

        controller = tds.commands.Repository()
        projects = controller.list(*(self.params.get('projects') or []))

        return self.render(dict(projects=projects))

    def render(self, *args, **kwargs):
        return self.view().generate_result(*args, **kwargs)
