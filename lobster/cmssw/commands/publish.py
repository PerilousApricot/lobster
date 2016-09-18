import daemon
import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid

from WMCore.DataStructs.LumiList import LumiList
from WMCore.FwkJobReport.Report import Report
from RestClient.ErrorHandling.RestClientExceptions import HTTPError
from WMCore.Storage.SiteLocalConfig import SiteLocalConfig
from WMCore.Storage.TrivialFileCatalog import readTFC
from dbs.apis.dbsClient import DbsApi

from lobster import util
from lobster.core.command import Command
from lobster.core.unit import UnitStore
from lobster.cmssw.dataset import Dataset

logger = logging.getLogger('lobster.publish.')


def hash_pset(fn):
    p = subprocess.Popen(['edmConfigHash', fn],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()

    if p.returncode != 0:
        logging.error('cannot calculate hash for "{0}": {1}'.format(fn, err))

    return out


def check_migration(status):
    successful = False

    if status == 0:
        logging.info('migration required')
    elif status == 1:
        logging.info('migration in process')
        time.sleep(15)
    elif status == 2:
        logging.info('migration successful')
        successful = True
    elif status == 3:
        logging.info('migration failed')

    return successful


def migrate_parents(parents, dbs):
    parent_blocks_to_migrate = []
    for parent in parents:
        logging.info(
            "looking in the local DBS for blocks associated with the parent lfn %s" % parent)
        parent_blocks = dbs['local'].listBlocks(logical_file_name=parent)
        if parent_blocks:
            logging.info('parent blocks found: no migration required')
        else:
            logging.info(
                'no parents blocks found in the local DBS, searching global DBS')
            dbs_output = dbs['global'].listBlocks(logical_file_name=parent)
            if dbs_output:
                parent_blocks_to_migrate.extend(
                    [entry['block_name'] for entry in dbs_output])
            else:
                logging.critical(
                    'unable to find parent blocks in the local or global DBS')
                logging.critical(
                    "verify parent blocks exist in DBS, or set 'migrate parents: False' in your lobster configuration")
                exit()

    parent_blocks_to_migrate = list(set(parent_blocks_to_migrate))
    if len(parent_blocks_to_migrate) > 0:
        logging.info('the following files will be migrated: %s' %
                     ', '.join(parent_blocks_to_migrate))

        migration_complete = False
        retries = 0
        while (retries < 5 and not migration_complete):
            migrated = []
            all_migrated = True
            for block in parent_blocks_to_migrate:
                migration_status = dbs[
                    'migrator'].statusMigration(block_name=block)
                if not migration_status:
                    logging.info('block will be migrated: %s' % block)
                    dbs_output = dbs['migrator'].submitMigration(
                        {'migration_url': 'https://cmsweb.cern.ch/dbs/prod/global/', 'migration_input': block})
                    all_migrated = False
                else:
                    migrated.append(block)
                    all_migrated = all_migrated and check_migration(
                        migration_status[0]['migration_status'])

            for block in migrated:
                migration_status = dbs[
                    'migrator'].statusMigration(block_name=block)
                all_migrated = migration_status and all_migrated and check_migration(
                    migration_status[0]['migration_status'])

            migration_complete = all_migrated
            logging.info(
                'migration not complete, waiting 15 seconds before checking again')
            time.sleep(15)
            retries += 1

        if not migration_complete:
            logging.critical('migration from global to local dbs failed')
            exit()
        else:
            logging.info('migration of all files complete')


class BlockDump(object):

    def __init__(self, username, dataset, dbs, publish_hash, publish_label, release, pset_hash, gtag):
        self.username = username
        self.dataset = dataset
        self.publish_label = publish_label
        self.publish_hash = publish_hash
        self.release = release
        self.pset_hash = pset_hash
        self.gtag = gtag
        self.dbs = dbs
        self.tasks = []

        storage_path = '/cvmfs/cms.cern.ch/SITECONF/%s/PhEDEx/storage.xml' % os.environ[
            'CMS_LOCAL_SITE']
        self.catalog = readTFC(storage_path)

        self.data = {'dataset_conf_list': [],
                     'file_conf_list': [],
                     'files': [],
                     'block': {},
                     'processing_era': {},
                     'acquisition_era': {},
                     'primds': {},
                     'dataset': {},
                     'file_parent_list': []}

        # see
        # https://twiki.cern.ch/twiki/bin/viewauth/CMS/DMWMPG_PrimaryDatasets#User_Data
        self.data['acquisition_era']['acquisition_era_name'] = self.username
        self.data['acquisition_era']['start_date'] = int(time.strftime('%Y'))

        self.data['processing_era']['create_by'] = 'lobster'
        self.data['processing_era']['processing_version'] = 1
        self.data['processing_era']['description'] = 'lobster'

        self.set_primary_dataset(dataset)
        self.set_dataset(1)
        self.set_block(1)

    def set_primary_dataset(self, prim_ds):
        output = self.dbs.listPrimaryDatasets(primary_ds_name=prim_ds)
        if len(output) > 0:
            self.data['primds'] = dict((k, v) for k, v in output[
                                       0].items() if k != 'primary_ds_id')
        else:
            logging.warning(
                "cannot find any information about the primary dataset %s in the global dbs" % prim_ds)
            logging.info(
                "using default parameters for primary dataset %s" % prim_ds)
            self.data['primds']['create_by'] = ''
            self.data['primds']['primary_ds_type'] = 'NOTSET'
            self.data['primds']['primary_ds_name'] = prim_ds
            self.data['primds']['creation_date'] = ''

    def set_dataset(self, version):
        # TODO: VERSION INCREMENTING
        processed_ds_name = '%s-%s-v%d' % (self.username,
                                           self.publish_label + '_' + self.publish_hash, version)

        self.data['dataset']['primary_ds_name'] = self.dataset
        self.data['dataset']['create_by'] = self.username
        self.data['dataset']['dataset_access_type'] = 'VALID'
        self.data['dataset']['data_tier_name'] = 'USER'
        self.data['dataset']['last_modified_by'] = self.username
        self.data['dataset']['creation_date'] = int(time.time())
        self.data['dataset']['processed_ds_name'] = processed_ds_name
        self.data['dataset']['last_modification_date'] = int(time.time())
        self.data['dataset'][
            'dataset'] = u'/%s/%s/USER' % (self.dataset, processed_ds_name)
        self.data['dataset']['processing_version'] = version
        self.data['dataset']['acquisition_era_name'] = self.username
        self.data['dataset']['physics_group_name'] = 'NoGroup'

    def set_block(self, version):
        site_config_path = '/cvmfs/cms.cern.ch/SITECONF/%s/taskConfig/site-local-config.xml' % os.environ[
            'CMS_LOCAL_SITE']

        self.data['block']['create_by'] = self.username
        self.data['block']['creation_date'] = int(time.time())
        self.data['block']['open_for_writing'] = 1
        self.data['block']['origin_site_name'] = SiteLocalConfig(
            site_config_path).localStageOutSEName()
        self.data['block']['block_name'] = self.data[
            'dataset']['dataset'] + '#' + str(uuid.uuid4())
        self.data['block']['file_count'] = 0
        self.data['block']['block_size'] = 0

    def reset(self):
        self.tasks = []
        self.data['files'] = []
        self.data['file_conf_list'] = []
        self.data['file_parent_list'] = []
        self.data['dataset_conf_list'] = []

        bname = self.data['block']['block_name']
        self.data['block']['block_name'] = bname[
            :bname.rfind('#') + 1] + str(uuid.uuid4())
        self.data['block']['file_count'] = 0
        self.data['block']['block_size'] = 0

    def add_dataset_config(self, app_name='cmsRun', output_label='Merged'):
        dataset_config = {'release_version': self.release,
                          'pset_hash': self.pset_hash,
                          'app_name': app_name,  # TODO PROPERLY
                          'output_module_label': output_label,  # TODO PROPERLY
                          'global_tag': self.gtag}

        self.data['dataset_conf_list'].append(dataset_config)

    def add_file_config(self, LFN, app_name='cmsRun', output_label='Merged'):
        conf_dict = {'release_version': self.release,
                     'pset_hash': self.pset_hash,
                     'lfn': LFN,
                     'app_name': app_name,  # TODO PROPERLY
                     'output_module_label': output_label,  # TODO PROPERLY
                     'global_tag': self.gtag}

        self.data['file_conf_list'].append(conf_dict)

    def add_file_parents(self, LFN, report):
        for fn in report['files']['infos'].keys():
            parent = {'logical_file_name': LFN, 'parent_logical_file_name': fn}
            if parent not in self.data['file_parent_list']:
                self.data['file_parent_list'].append(parent)

    def add_file(self, LFN, output, task, merged_task):
        def lumi_dict_to_list(d):
            for run in d.keys():
                for lumi in d[run]:
                    yield {'run_num': run, 'lumi_section_num': lumi}
        PFN = self.catalog.matchLFN('direct', LFN)
        cksum = 0
        size = 0
        try:
            c = subprocess.Popen('cksum %s' %
                                 PFN, shell=True, stdout=subprocess.PIPE)
            cksum, size = c.stdout.read().split()[:2]
        except Exception:
            logging.warning("error calculating checksum")

        file_dict = {'check_sum': int(cksum),
                     'file_lumi_list': lumi_dict_to_list(output['runs']),
                     'adler32': output['adler32'],
                     'event_count': int(output['events']),
                     'file_type': output['FileType'],
                     'last_modified_by': self.username,
                     'logical_file_name': LFN,
                     'file_size': int(size),
                     'last_modification_date': int(os.path.getmtime(PFN))}

        self.data['files'].append(file_dict)

        self.data['block']['block_size'] += int(size)
        self.data['block']['file_count'] += 1

        self.tasks += [(task, merged_task)]

    def get_LFN(self, PFN):
        # see
        # https://twiki.cern.ch/twiki/bin/viewauth/CMS/DMWMPG_Namespace#store_user_and_store_temp_user
        LFN = os.path.join('/store/user',
                           self.username,
                           self.dataset,
                           self.publish_label + '_' + self.publish_hash,
                           os.path.basename(PFN))

        return LFN

    def get_matched_PFN(self, PFN, LFN):
        matched = self.catalog.matchLFN('direct', LFN)
        matched_dir = os.path.dirname(matched)
        if os.path.isfile(PFN):
            if not os.path.isfile(matched):
                if not os.path.isdir(matched_dir):
                    os.makedirs(matched_dir)
                shutil.move(PFN, matched_dir)
        else:
            if not os.path.isfile(matched):
                return None

        return matched

    def get_publish_update(self):
        update = [(self.data['block']['block_name'], task, merge_task)
                  for task, merge_task in self.tasks]

        return update

    def __getitem__(self, item):
        return self.data[item]

    def __setitem__(self, key, value):
        self.data[key] = value


class Publish(Command):

    @property
    def help(self):
        return 'publish results in the CMS Data Aggregation System'

    def setup(self, argparser):
        argparser.add_argument('--migrate-parents', dest='migrate_parents',
                               default=False, help='migrate parents to local DBS')
        argparser.add_argument('--block-size', dest='block_size', type=int, default=400,
                               help='number of files to publish per file block.')
        argparser.add_argument(
            'datasets', nargs='*', help='dataset labels to publish (default is all datasets)')
        argparser.add_argument('-f', '--foreground', action='store_true', default=False,
                               help='do not daemonize;  run in the foreground instead')

    def run(self, args):
        config = args.config

        if len(args.datasets) == 0:
            args.datasets = [workflow['label']
                             for workflow in config.get('workflows', [])]

        workdir = config['workdir']
        user = config.get('publish user', os.environ['USER'])
        publish_instance = config.get('dbs instance', 'phys03')
        published = {'dataset': '', 'dbs instance': publish_instance}

        if not args.foreground:
            ttyfile = open(os.path.join(workdir, 'publish.err'), 'a')
            logger.info("saving stderr and stdout to {0}".format(
                os.path.join(workdir, 'publish.err')))

        with daemon.DaemonContext(
                detach_process=not args.foreground,
                stdout=sys.stdout if args.foreground else ttyfile,
                stderr=sys.stderr if args.foreground else ttyfile,
                files_preserve=[args.preserve],
                working_directory=workdir,
                pidfile=util.get_lock(workdir)):
            db = UnitStore(config)

            dbs = {}
            for path, key in [[('global', 'DBSReader'), 'global'],
                              [(publish_instance, 'DBSWriter'), 'local'],
                              [(publish_instance, 'DBSReader'), 'reader'],
                              [(publish_instance, 'DBSMigrate'), 'migrator']]:
                dbs[key] = DbsApi(
                    'https://cmsweb.cern.ch/dbs/prod/{0}/'.format(os.path.join(*path)))

            for label in args.datasets:
                (dset,
                 stageout_path,
                 release,
                 gtag,
                 publish_label,
                 cfg,
                 pset_hash,
                 ds_id,
                 publish_hash) = [str(x) for x in db.dataset_info(label)]

                dset = dset.strip('/').split('/')[0]
                if not pset_hash or pset_hash == 'None':
                    logger.info(
                        'the parameter set hash has not been calculated')
                    logger.info(
                        'calculating parameter set hash now (may take a few minutes)')
                    cfg_path = os.path.join(
                        workdir, label, os.path.basename(cfg))
                    tmp_path = cfg_path.replace('.py', '_tmp.py')
                    with open(cfg_path, 'r') as infile:
                        with open(tmp_path, 'w') as outfile:
                            fix = "import sys \nif not hasattr(sys, 'argv'): sys.argv = ['{0}']\n"
                            outfile.write(fix.format(tmp_path))
                            outfile.write(infile.read())
                    try:
                        pset_hash = hash_pset(tmp_path)
                        db.update_pset_hash(pset_hash, label)
                    except Exception:
                        logger.warning(
                            'error calculating the cmssw parameter set hash')
                    os.remove(tmp_path)

                block = BlockDump(user, dset, dbs[
                                  'global'], publish_hash, publish_label, release, pset_hash, gtag)

                if len(dbs['local'].listAcquisitionEras(acquisition_era_name=user)) == 0:
                    try:
                        dbs['local'].insertAcquisitionEra(
                            {'acquisition_era_name': user})
                    except Exception, ex:
                        logger.warn(ex)
                try:
                    dbs['local'].insertPrimaryDataset(block.data['primds'])
                    dbs['local'].insertDataset(block.data['dataset'])
                except Exception, ex:
                    logger.warn(ex)
                    raise

                tasks = db.finished_tasks(label)

                first_task = 0
                inserted = False
                logger.info('found %d successful %s tasks to publish' %
                            (len(tasks), label))
                missing = []
                while first_task < len(tasks):
                    block.reset()
                    chunk = tasks[first_task:first_task + args.block_size]
                    logger.info('preparing DBS entry for %i task block: %s' % (
                        len(chunk), block['block']['block_name']))

                    for task, merged_task in chunk:
                        id = merged_task if merged_task else task

                        f = gzip.open(os.path.join(
                            workdir, label, util.id2dir(id), 'report.xml.gz'), 'r')
                        report = Report.readtaskReport(f)[0]

                        with open(os.path.join(workdir, label, 'successful', util.id2dir(id), 'report.json')) as f:
                            report = json.load(f)
                        with open(os.path.join(workdir, label, 'successful', util.id2dir(id), 'parameters.json')) as f:
                            parameters = json.load(f)

                        local, remote = parameters['output files'][0]
                        PFN = os.path.join(
                            stageout_path, os.path.basename(remote))
                        LFN = block.get_LFN(PFN)
                        matched_PFN = block.get_matched_PFN(PFN, LFN)
                        if not matched_PFN:
                            logger.warn(
                                'could not find expected output for task(s) {0}'.format(task))
                            missing.append(task)
                        else:
                            fileinfo = report['files']['output_info'][local]
                            logger.info('adding %s to block' % LFN)
                            block.add_file_config(LFN)
                            block.add_file(LFN, fileinfo, task, merged_task)
                            block.add_dataset_config()
                            if args.migrate_parents:
                                block.add_file_parents(LFN, report)

                    if args.migrate_parents:
                        parents_to_migrate = list(
                            set([p['parent_logical_file_name'] for p in block['file_parent_list']]))
                        migrate_parents(parents_to_migrate, dbs)

                    if len(block.data['files']) > 0:
                        try:
                            inserted = True
                            dbs['local'].insertBulkBlock(block.data)
                            db.update_published(block.get_publish_update())
                            logger.info('block inserted: %s' %
                                        block['block']['block_name'])
                        except HTTPError, e:
                            logger.critical(e)

                    first_task += args.block_size

                if inserted:
                    published.update({'dataset': block['dataset']['dataset']})
                    info = Dataset(published).get_info(published)
                    lumis = LumiList(lumis=sum(info.lumis.values(), []))
                    filename = os.path.join(workdir, label, 'published.json')
                    lumis.writeJSON(filename)

                    logger.info('publishing dataset %s complete' % label)
                    logger.info('json file of published runs and lumis saved to %s' % filename)

                if len(missing) > 0:
                    template = "the following task(s) have not been published because their output could not be found: {0}"
                    logger.warning(template.format(
                        ", ".join(map(str, missing))))
