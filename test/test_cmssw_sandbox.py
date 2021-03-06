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
        version, arch, box = sandbox.package([os.path.dirname(__file__)], self.workdir)
        assert version == 'CMSSW_2_3_4'
        assert arch == 'slc1_234'

    def test_version(self):
        sandbox = lobster.cmssw.sandbox.Sandbox(release='data/sandbox/CMSSW_1_2_3')
        version, arch, box = sandbox.package([os.path.dirname(__file__)], self.workdir)
        assert version == 'CMSSW_2_3_4'
        assert arch == 'slc1_234'

    def test_include(self):
        sandbox = lobster.cmssw.sandbox.Sandbox(release='data/sandbox/CMSSW_1_2_3', include=['Foo/mydir'])
        version, arch, box = sandbox.package([os.path.dirname(__file__)], self.workdir)
        files = [f.name for f in tarfile.open(box)]
        assert 'CMSSW_2_3_4/src/Foo/mydir' in files

    def test_recycle(self):
        sandbox = lobster.cmssw.sandbox.Sandbox(release='data/sandbox/CMSSW_1_2_3', include=['Foo/mydir'])
        version, arch, box = sandbox.package([os.path.dirname(__file__)], self.workdir)

        tmpdir = os.path.join(self.workdir, 'tmpbox')
        os.makedirs(tmpdir)
        shutil.move(box, tmpdir)
        box = os.path.join(tmpdir, os.path.basename(box))

        sandbox2 = lobster.cmssw.sandbox.Sandbox(recycle=box)
        version2, arch2, box2 = sandbox2.package([os.path.dirname(__file__)], self.workdir)

        assert version2 == version
        assert arch2 == arch
