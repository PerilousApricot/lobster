import os
import shutil
import tarfile
import tempfile
import unittest

import lobster.cmssw.sandbox


class TestSandbox(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workdir)

    def test_localrt(self):
        os.environ['LOCALRT'] = 'data/sandbox/CMSSW_1_2_3'
        sandbox = lobster.cmssw.sandbox.Sandbox()
        version, box = sandbox.package([os.path.dirname(__file__)], self.workdir)
        assert version == 'CMSSW_1_2_3'

    def test_version(self):
        sandbox = lobster.cmssw.sandbox.Sandbox(release='data/sandbox/CMSSW_1_2_3')
        version, box = sandbox.package([os.path.dirname(__file__)], self.workdir)
        assert version == 'CMSSW_1_2_3'

    def test_include(self):
        sandbox = lobster.cmssw.sandbox.Sandbox(release='data/sandbox/CMSSW_1_2_3', include=['Foo/mydir'])
        version, box = sandbox.package([os.path.dirname(__file__)], self.workdir)
        files = [f.name for f in tarfile.open(box)]
        assert 'CMSSW_1_2_3/src/Foo/mydir' in files
