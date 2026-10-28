"""Project discovery and CLI behavior with projects stored under videos/."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import ai4video
import review


class ProjectLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai4video-projects-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(ai4video.ROOT/'ai4video.py', self.root/'ai4video.py')

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.root/'ai4video.py'), *args],
            cwd=self.root, capture_output=True, text=True, check=True)

    def test_init_register_and_list_use_videos(self):
        created = self.cli('init', 'new-video', '--title', 'New video')
        folder = self.root/'videos'/'new-video'
        self.assertEqual(Path(created.stdout.strip()), folder)
        self.assertTrue((folder/'project.json').is_file())
        self.assertTrue((folder/'clips').is_dir())
        existing = self.root/'videos'/'existing-video'
        existing.mkdir()
        self.cli('register', 'existing-video', '--title', 'Existing video')
        decoy = self.root/'old-video'
        decoy.mkdir()
        shutil.copyfile(folder/'project.json', decoy/'project.json')
        listing = self.cli('list').stdout
        self.assertIn('new-video\tdraft\t0 clips\tNew video', listing)
        self.assertIn('existing-video\tdraft\t0 clips\tExisting video', listing)
        self.assertNotIn('old-video', listing)

    def test_run_uses_project_build_and_working_directory(self):
        self.cli('init', 'new-video', '--title', 'New video')
        folder = self.root/'videos'/'new-video'
        (self.root/'.venv').symlink_to(ai4video.ROOT/'.venv', target_is_directory=True)
        (folder/'build.py').write_text(
            'from pathlib import Path\nimport sys\n'
            'print(Path.cwd())\nprint(sys.argv[1])\n')
        result = self.cli('run', 'new-video', 'check')
        self.assertEqual(result.stdout.splitlines(), [str(folder), 'check'])

    def test_reviewer_loads_project_from_videos(self):
        self.cli('init', 'new-video', '--title', 'New video')
        folder = self.root/'videos'/'new-video'
        (folder/'visuals.py').write_text(
            'from PIL import Image\n'
            'def frame(scene, t):\n'
            '    return Image.new("RGB", (1920, 1080), "navy")\n')
        (folder/'timeline.json').write_text(json.dumps({
            'scenes': [{'index': 1, 'title': 'Opening', 'duration': 2}]}))
        catalog = review.ProjectCatalog(root=self.root/'videos')
        self.assertEqual(catalog.projects(), [
            {'id': 'new-video', 'title': 'New video', 'ready': True}])
        runtime = catalog.get('new-video')
        self.assertEqual(runtime.root, folder)
        self.assertEqual(runtime.state()['cut_count'], 1)
        self.assertTrue(runtime.frame(1, 0)[0])

    def test_checkout_without_videos_lists_no_projects_and_explains_setup(self):
        self.assertEqual(self.cli('list').stdout, '')
        shutil.copyfile(review.ROOT/'review.py', self.root/'review.py')
        result = subprocess.run([sys.executable, str(self.root/'review.py')],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('videos/<프로젝트>/', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
