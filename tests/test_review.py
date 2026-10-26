"""Regression checks for shared render code, cache invalidation, and recovery."""
from io import BytesIO
import shutil
from pathlib import Path
import tempfile
import unittest

from PIL import Image

import review

TRITON = review.ROOT/'triton-tiled-matmul'


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='triton-review-test-')
        self.root = Path(self.temp.name)
        for file in ('build.py', 'visuals.py', 'scenes.py', 'elevenlabs_tts.py', 'script.md', 'review_adapter.py', 'project.json'):
            shutil.copyfile(TRITON/file, self.root/file)
        (self.root/'audio').symlink_to(TRITON/'audio', target_is_directory=True)
        self.runtime = review.PreviewRuntime(self.root,'triton-tiled-matmul')

    def tearDown(self):
        self.temp.cleanup()

    def test_frames_use_the_export_renderer_and_cache(self):
        state = self.runtime.state()
        self.assertEqual(state['cut_count'], 66)
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

    def test_numeric_tiles_sum_to_the_full_matrix_product(self):
        self.runtime.refresh()
        scenes = self.runtime.load_module('scenes')
        self.assertEqual(scenes.FIRST, [[1, 4], [5, 16]])
        self.assertEqual(scenes.SECOND, [[11, 3], [23, 7]])
        self.assertEqual(scenes.FINAL, [[12, 7], [28, 23]])
        for r in range(2):
            for c in range(2):
                self.assertEqual(scenes.FIRST[r][c]+scenes.SECOND[r][c], scenes.C_VALUES[r][c])

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
        self.assertEqual(recovered['cut_count'], 66)

    def test_inserted_cuts_preserve_existing_note_ids_and_audio(self):
        cuts=self.runtime.state()['scenes'][0]['cuts']
        self.assertEqual([c['id'] for c in cuts],
                         ['1-01','1-01a','1-01b','1-01c','1-02','1-03','1-04','1-05'])
        memory=next(c for c in cuts if c['id']=='1-02')
        partition=next(c for c in cuts if c['id']=='1-04')
        self.assertEqual(memory['key'],'memory')
        self.assertEqual(partition['key'],'partition')
        self.assertIn('/audio/01-01.mp3',memory['audio_url'])

    def test_hbm_explanation_shows_motion_without_numeric_examples(self):
        self.runtime.refresh()
        visual=self.runtime.visuals
        scene=self.runtime.scenes[1]
        with self.runtime.imports():
            for beat in scene['beats']:
                if not beat['key'].startswith('hbm_'):
                    continue
                frames=[]
                for fraction in (.15,.55,.85):
                    visual.TEXT_AUDIT=[]
                    frame=visual.frame(scene,beat['start']+beat['duration']*fraction)
                    for label,_ in visual.TEXT_AUDIT:
                        if label=='01' or label.endswith('s') and 's / ' in label:
                            continue
                        self.assertFalse(any(c.isdigit() for c in label),label)
                    frames.append(frame.crop((1250,520,1820,945)).tobytes())
                self.assertNotEqual(frames[0],frames[-1],beat['key'])
        visual.TEXT_AUDIT=None

    def test_dot_animation_completes_three_examples_in_each_stage(self):
        self.runtime.refresh()
        visual=self.runtime.visuals
        scene=self.runtime.scenes[1]
        beat=scene['beats'][0]
        phases=beat['visual_phases']
        groups=[]
        for group,(start,end) in enumerate(zip(phases,phases[1:])):
            results=[]
            for example in range(3):
                p=start+(end-start)*(example+.95)/3
                state=visual.dot_state(p*beat['duration'],beat['duration'],phases)
                self.assertEqual(state['group'],group)
                self.assertEqual(state['example'],example)
                self.assertGreaterEqual(state['progress'],.9)
                self.assertEqual(len(state['completed']),group*3+example)
                results.append((state['row'],state['col']))
            groups.append(results)
        self.assertEqual(len(groups),2)
        self.assertEqual(len({cell for group in groups for cell in group}),6)
        self.assertEqual(len({r for r,c in groups[0]}),1)
        self.assertEqual(len({c for r,c in groups[0]}),3)
        self.assertEqual(len({r for r,c in groups[1]}),3)
        self.assertEqual(len({c for r,c in groups[1]}),1)
        self.assertEqual(groups[0][-1][1],groups[1][0][1])
        sequence=[cell for group in groups for cell in group]
        for a,b in zip(sequence,sequence[1:]):
            self.assertNotEqual(a[0]!=b[0],a[1]!=b[1])
        # The first completed output stays filled after switching to A-row motion.
        with self.runtime.imports():
            frame=visual.frame(scene,phases[1]*beat['duration']+.1)
        x,y,_,_=visual.MATRICES['C']
        row,col=groups[0][0]
        self.assertEqual(frame.getpixel((x+col*visual.CELL,y+row*visual.CELL)),
                         visual.mix(visual.BG,visual.PURPLE,.68))

    def test_changed_narration_can_preview_but_export_stays_strict(self):
        self.runtime.refresh()
        path = self.root/'script.md'
        path.write_text(path.read_text().replace('여기서 타일링을 결정하는 숫자는 세 가지입니다.',
                                                '여기서 타일링을 결정하는 숫자는 세 가지가 있습니다.'))
        state = self.runtime.state()
        cut = state['scenes'][1]['cuts'][1]
        self.assertTrue(cut['audio_stale'])
        self.assertIsNone(cut['audio_url'])
        self.assertTrue(self.runtime.frame(2, cut['start'])[0])
        with self.assertRaisesRegex(RuntimeError, 'Narration is stale'):
            self.runtime.load_module('build').timeline()

    def test_invalid_frame_requests_are_rejected(self):
        for args in ((99, 0), (1, float('nan')), (1, 0, 123), (1, 0, 960, 'gif')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.runtime.frame(*args)

    def test_notes_are_durable_and_do_not_invalidate_frames(self):
        before=self.runtime.state()['version']
        data=self.runtime.save_note(dict(cut_id='2-03',text='BM을 왼쪽으로\n조금 옮겨 주세요.',scene_time=15.1))
        note=data['notes']['2-03']
        self.assertEqual(note['scene_index'],2)
        self.assertEqual(note['status'],'pending')
        self.assertAlmostEqual(note['scene_time'],15.1)
        self.assertGreater(note['cut_time'],0)
        self.assertEqual(self.runtime.state()['version'],before)
        restarted=review.PreviewRuntime(self.root,'triton-tiled-matmul')
        self.assertEqual(restarted.read_notes()['notes']['2-03']['text'],note['text'])
        self.runtime.save_note(dict(cut_id='2-03',text='과거 메모',import_if_absent=True))
        self.assertEqual(self.runtime.read_notes()['notes']['2-03']['text'],note['text'])
        self.runtime.save_note(dict(cut_id='2-03',text=''))
        self.assertEqual(self.runtime.read_notes()['notes']['2-03']['status'],'cleared')

    def test_note_validation(self):
        for body in [dict(cut_id='../oops',text='x'),dict(cut_id='2-03',text='x'*20001),
                     dict(cut_id='2-03',text='x',scene_time=float('nan'))]:
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
