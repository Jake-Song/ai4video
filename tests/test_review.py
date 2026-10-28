"""Regression checks for shared render code, cache invalidation, and recovery."""
from io import BytesIO
import tempfile
import unittest

from PIL import Image

import review
from review_fixture import create_project


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-test-')
        self.root = create_project(self.temp.name)
        self.runtime = review.PreviewRuntime(self.root, 'sample-video')

    def tearDown(self):
        self.temp.cleanup()

    def test_frames_use_the_export_renderer_and_cache(self):
        state = self.runtime.state()
        self.assertEqual(state['cut_count'], 4)
        data, number, cached, version = self.runtime.frame(1, 3, 960)
        self.assertEqual(number, 90)
        self.assertFalse(cached)
        self.assertEqual(Image.open(BytesIO(data)).size, (960, 540))
        self.assertEqual(self.runtime.frame(1, 3, 960)[2], True)
        png, number, _, _ = self.runtime.frame(2, 12, 1920, 'png')
        expected = self.runtime.visuals.frame(self.runtime.scenes[2], number/30)
        actual = Image.open(BytesIO(png))
        self.assertEqual(actual.size, (1920, 1080))
        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(version, state['version'])

    def test_source_change_reloads_pixels_and_invalidates_cache(self):
        old = self.runtime.frame(1, 3, 960)
        path = self.root/'visuals.py'
        path.write_text(path.read_text().replace(self.runtime.visuals.BLUE, '#c53961'))
        new = self.runtime.frame(1, 3, 960)
        self.assertNotEqual(old[3], new[3])
        self.assertNotEqual(old[0], new[0])
        self.assertFalse(new[2])
        with self.assertRaises(review.RevisionChanged):
            self.runtime.frame(1, 3, expected_version=old[3])

    def test_syntax_error_keeps_good_revision_and_recovers_after_undo(self):
        good = self.runtime.state()['version']
        path = self.root/'visuals.py'
        original = path.read_text()
        path.write_text(original+'\ninvalid syntax ???\n')
        with self.assertRaises(ValueError):
            self.runtime.state()
        self.assertEqual(self.runtime.version, good)
        path.write_text(original)
        recovered = self.runtime.state()
        self.assertNotEqual(recovered['version'], good)
        self.assertIsNone(self.runtime.error)
        self.assertEqual(recovered['cut_count'], 4)

    def test_invalid_frame_requests_are_rejected(self):
        for args in ((99, 0), (1, float('nan')), (1, 0, 123), (1, 0, 960, 'gif')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.runtime.frame(*args)

    def test_notes_are_durable_and_do_not_invalidate_frames(self):
        before=self.runtime.state()['version']
        data=self.runtime.save_note(dict(cut_id='2-02',text='BM을 왼쪽으로\n조금 옮겨 주세요.',scene_time=15.1))
        note=data['notes']['2-02']
        self.assertEqual(note['scene_index'],2)
        self.assertEqual(note['status'],'pending')
        self.assertAlmostEqual(note['scene_time'],15.1)
        self.assertGreater(note['cut_time'],0)
        self.assertEqual(self.runtime.state()['version'],before)
        restarted=review.PreviewRuntime(self.root,'sample-video')
        self.assertEqual(restarted.read_notes()['notes']['2-02']['text'],note['text'])
        self.runtime.save_note(dict(cut_id='2-02',text='과거 메모',import_if_absent=True))
        self.assertEqual(self.runtime.read_notes()['notes']['2-02']['text'],note['text'])
        self.runtime.save_note(dict(cut_id='2-02',text=''))
        self.assertEqual(self.runtime.read_notes()['notes']['2-02']['status'],'cleared')

    def test_note_validation(self):
        for body in [dict(cut_id='../oops',text='x'),dict(cut_id='2-02',text='x'*20001),
                     dict(cut_id='2-02',text='x',scene_time=float('nan'))]:
            with self.subTest(body=str(body)[:80]),self.assertRaises(ValueError):
                self.runtime.save_note(body)

    def test_resolution_cannot_acknowledge_a_newer_user_edit(self):
        self.runtime.save_note(dict(cut_id='1-01',text='첫 요청'))
        self.runtime.save_note(dict(cut_id='1-01',text='새 요청'))
        with self.assertRaises(ValueError):
            self.runtime.save_note(dict(cut_id='1-01',text='첫 요청',status='resolved',expected_revision=1))
        self.assertEqual(self.runtime.read_notes()['notes']['1-01']['status'],'pending')
        self.runtime.save_note(dict(cut_id='1-01',text='새 요청',status='resolved',expected_revision=2))
        cleared=self.runtime.read_notes()['notes']['1-01']
        self.assertEqual(cleared['status'],'cleared')
        self.assertEqual(cleared['text'],'')
        self.assertNotIn('resolution',cleared)
        self.runtime.save_note(dict(cut_id='1-01',text='옛 브라우저의 메모',import_if_absent=True))
        self.assertEqual(self.runtime.read_notes()['notes']['1-01']['text'],'')


if __name__ == '__main__':
    unittest.main()
