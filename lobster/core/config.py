import datetime
import getpass
import os
import pickle

from lobster.core.workflow import Category
from lobster.util import Configurable


class Items(object):

    """
    Collection similar to `namedtuple`, but can be pickled.

    Parameters
    ----------
        args : list
            List of objects the collection should contain
        key : function
            Function to obtain the key of an object in the collection
    """

    def __init__(self, args, key=None):
        for arg in args:
            attr = key(arg) if key else arg
            if attr in self.__dict__:
                raise AttributeError("Attribute already defined: {}".format(attr))
            setattr(self, attr, arg)
        self.__sequence = args

    def __iter__(self):
        return iter(self.__sequence)

    def __len__(self):
        return len(self.__sequence)

    def __getitem__(self, n):
        return self.__sequence[n]

    def __repr__(self):
        if len(self.__sequence) == 0:
            return '[]'

        def indent(text):
            lines = text.splitlines()
            if len(lines) <= 1:
                return text
            return "\n".join("    " + l for l in lines).strip()
        return '[\n    {}\n]'.format(',\n    '.join(indent(repr(e)) for e in self.__sequence))


class Config(Configurable):

    """
    Top-level Lobster configuration object

    This configuration object will fully specify a Lobster project,
    including several :class:`~lobster.core.workflow.Workflow` instances
    and a :class:`~lobster.se.StorageConfiguration`.

    Parameters
    ----------
        workdir : str
            The working directory to be used for the project.  Note that
            this should be on a local filesystem to avoid problems with the
            database.
        storage : StorageConfiguration
            The configuration for the storage element for output and input
            files.
        workflows : list
            A list of :class:`~lobster.core.workflow.Workflow` to process.
        label : str
            A string to identify this project by.  This will be used in the
            CMS dashboard, where it appears as
            ``lobster_<user>_<label>_<hash>``, and in conjunction with
            `WorkQueue`, where the project will be referred to as
            ``lobster_<user>_<label>``.  The default is the date in the
            format `YYYYmmdd`.
        advanced : AdvancedOptions
            More options for advanced users.
        plotdir : str
            A directory to store monitoring pages in.
        foremen_logs : list
            A list of :class:`str` pointing to the `WorkQueue` foremen logs.
    """

    _mutable = {}

    def __init__(self, workdir, storage, workflows, label=None, advanced=None, plotdir=None, foremen_logs=None,
                 base_directory=None, base_configuration=None, startup_directory=None, elk=None):
        """
        Top-level configuration object for Lobster
        """
        self.label = '{}_{}'.format(
            getpass.getuser(),
            label or datetime.datetime.now().strftime('%Y%m%d')
        )
        self.workdir = os.path.expanduser(os.path.expandvars(workdir))
        if plotdir is not None:
            self.plotdir = os.path.expanduser(os.path.expandvars(plotdir))
        else:
            self.plotdir = None
        self.foremen_logs = foremen_logs
        self.storage = storage
        self.workflows = Items(workflows, key=lambda w: w.label)
        self.advanced = advanced if advanced else AdvancedOptions()
        self.elk = elk

        cats = list(set([w.category for w in workflows])) + [Category(name='merge', cores=1)]
        self.categories = Items(cats, key=lambda c: c.name)

        self.base_directory = base_directory
        self.base_configuration = base_configuration
        self.startup_directory = startup_directory

        self.storage.activate()

    def __repr__(self):
        s = "from lobster import cmssw\nfrom lobster.core import *\n\n"
        for cat in self.categories:
            if cat.name == 'merge':
                continue
            s += "category_{} = {}\n\n".format(cat.name, repr(cat))
        for wflow in self.workflows:
            s += "workflow_{} = {}\n\n".format(wflow.label, repr(wflow))
        override = {'workflows': '[{}]'.format(
            ', '.join(['workflow_' + w.label for w in self.workflows]))}
        s += "config = " + Configurable.__repr__(self, override)
        return s

    @classmethod
    def load(cls, path):
        try:
            with open(os.path.join(path, 'config.pkl'), 'rb') as f:
                cfg = pickle.load(f)
                cfg.storage.activate(failures=False)
                return cfg
        except IOError as e:
            print e
            raise IOError("can't load configuration from {0}".format(
                os.path.join(path, 'config.pkl')))

    def save(self):
        with open(os.path.join(self.workdir, 'config.pkl'), 'wb') as f:
            pickle.dump(self, f)


class AdvancedOptions(Configurable):

    """
    Advanced options for tuning Lobster

    Attributes modifiable at runtime:

    * `payload`
    * `threshold_for_failure`
    * `threshold_for_skipping`

    Parameters
    ----------
        abort_threshold : int
            After how many successful tasks outliers in runtime should be
            killed.
        abort_multiplier : int
            How many standard deviations a task is allowed to go over the
            average task runtime.
        bad_exit_codes : list
            A list of exit codes that are considered to come from bad
            workers.  As soon as a task returns with an exit code from this
            list, the worker it ran on will be blacklisted and no more
            tasks send to it.
        dashboard : :class:`~lobster.cmssw.Dashboard`
            Use the CMS dashboard to report task status.  Set or `False` to
            disable.
        dump_core : bool
            Produce core dumps.  Useful to debug `WorkQueue`.
        email : str
            The email address you want to receive emails from Lobster.
        full_monitoring : bool
            Produce full monitoring output.  Useful to debug `WorkQueue`.
        log_level : int
            How much logging output to show.  Goes from 1 to 5, where 1 is
            the most verbose (including a lot of debug output), and 5 is
            practically quiet.
        osg_version : str
            The version of OSG you want lobster to run on.
        payload : int
            How many tasks to keep in the queue (minimum).  Note that the
            payload will increase with the number of cores available to
            Lobster.  This is just the minimum with no workers connected.
        proxy : :class:`~lobster.cmssw.Proxy`
            An authentication mechanism to access data.  Set to `False` to
            disable.
        threshold_for_failure : int
            How often a single unit may fail to be processed before Lobster
            will not attempt to process it any longer.
        threshold_for_skipping : int
            How often a single file may fail to be accessed before Lobster
            will not attempt to process it any longer.
        wq_max_retries : int
            How often `WorkQueue` will attempt to process a task before
            handing it back to Lobster.  `WorkQueue` will only reprocess
            evicted tasks automatically.
        xrootd_servers : list
            A list of xrootd servers to use to access remote data.
            Defaults to `cmsxrootd.fnal.gov`.
    """

    _mutable = {
        'bad_exit_codes': (None, [], False),
        'payload': (None, [], False),
        'threshold_for_failure': ('source.update_paused', [], False),
        'threshold_for_skipping': ('source.update_paused', [], False),
        'xrootd_servers': ('source.copy_siteconf', [], False)
    }

    def __init__(self,
                 abort_threshold=10,
                 abort_multiplier=4,
                 bad_exit_codes=None,
                 dashboard=None,
                 dump_core=False,
                 email=None,
                 full_monitoring=False,
                 log_level=2,
                 osg_version=None,
                 payload=10,
                 proxy=None,
                 threshold_for_failure=30,
                 threshold_for_skipping=30,
                 wq_max_retries=10,
                 xrootd_servers=None):
        from lobster import cmssw

        self.osg_version = osg_version

        if not osg_version:
            osg_location = os.environ.get("OSG_LOCATION")
            if not osg_location:
                raise AttributeError("No OSG version specified or in the environment.")
            self.osg_version = osg_location.rsplit('/', 3)[1]

        self.abort_threshold = abort_threshold
        self.abort_multiplier = abort_multiplier
        self.bad_exit_codes = bad_exit_codes if bad_exit_codes else [169]
        self.dashboard = dashboard
        if dashboard is None:
            self.dashboard = cmssw.Dashboard()
        elif not dashboard:
            self.dashboard = cmssw.Monitor()
        self.dump_core = dump_core
        self.email = email
        self.full_monitoring = full_monitoring
        self.log_level = log_level
        self.payload = payload
        self.proxy = proxy if proxy is not None else cmssw.Proxy()
        self.threshold_for_failure = threshold_for_failure
        self.threshold_for_skipping = threshold_for_skipping
        self.wq_max_retries = wq_max_retries
        self.xrootd_servers = xrootd_servers if xrootd_servers else ['cmsxrootd.fnal.gov']
