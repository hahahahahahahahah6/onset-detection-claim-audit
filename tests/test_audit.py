import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from onset_detection_claim_audit import __version__, phrases
from onset_detection_claim_audit.audit import GENERIC, audit, claims, has_evidence, main

EXPECTED_ONSET = ('onset detection', 'detects onsets', 'detects onset', 'identifies onsets', 'identifies onset', 'detects note onsets', 'identifies note onsets', 'detects musical onsets', 'note onset detection', 'musical onset detection', 'audio onset detection', 'music onset detection', 'onset detection for music', 'onset detection for audio', 'automatic onset detection', 'onset detector', 'detects the onset of a note', 'detects the onsets of notes', 'identifies the onset of a note', 'detects onset times', 'identifies onset times', 'finds onsets', 'finds onset times', 'extracts onsets', 'onset time detection', 'note onset recognition', 'onset recognition', 'onset estimation', 'estimates onsets', 'predicts onsets', 'onset tracking', 'tracks onsets', 'detects song onsets', 'detects track onsets', 'identifies song onsets', 'song onset detection', 'track onset detection', 'audio onset recognition', 'music onset recognition', 'onset analysis', 'analyzes onsets', 'onset detection algorithm', 'onset detection system', 'detects audio onsets', 'identifies audio onsets', 'detects music onsets', 'identifies music onsets', 'onset detection feature', 'onset detection capability', 'onset detection tool')
EXPECTED_NOONSET = ('no onset detection', 'does not detect onsets', 'does not detect onset', 'without onset detection', 'does not identify onsets', 'does not identify onset', 'does not detect note onsets', 'does not identify note onsets', 'no note onset detection', 'does not detect musical onsets', 'no musical onset detection', 'no audio onset detection', 'does not detect audio onsets', 'does not identify audio onsets', 'no music onset detection', 'does not detect music onsets', 'no onset recognition', 'does not recognize onsets', 'does not detect onset times', 'no onset time detection', 'onset detection not supported', 'does not find onsets', 'does not extract onsets', 'no onset detector')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        lists = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
        self.assertEqual(tuple(lists['ONSET']), EXPECTED_ONSET)
        self.assertEqual(tuple(lists['NOONSET']), EXPECTED_NOONSET)
        self.assertEqual(len(EXPECTED_ONSET), 50)
        self.assertEqual(len(EXPECTED_NOONSET), 24)

    def test_every_phrase(self):
        for phrase in EXPECTED_ONSET:
            with self.subTest(phrase=phrase):
                self.assertTrue(claims(phrase)[0])
        for phrase in EXPECTED_NOONSET:
            with self.subTest(phrase=phrase):
                pos, neg = claims(phrase)
                self.assertEqual(pos, [])
                self.assertEqual(neg, [phrase])

    def test_normalization_and_boundaries(self):
        self.assertEqual(claims("It doesn't detect onsets."), ([], ['does not detect onsets']))
        self.assertEqual(claims('AUTOMATIC ONSET-DETECTION\n for audio')[0], ['automatic onset detection'])
        self.assertEqual(claims('xdetects onsetsx'), ([], []))
        self.assertEqual(claims('detects\n\nonsets'), ([], []))
        self.assertEqual(claims('onset detection algorithm')[0], ['onset detection algorithm'])
        self.assertEqual(claims('does not detect onsets; detects onsets')[0], ['detects onsets'])

    def test_fences_and_inline(self):
        for marker in ('```', '~~~', '   ````', '  ~~~~'):
            with self.subTest(marker=marker):
                self.assertEqual(claims(marker + 'python\nonset detection\n' + marker), ([], []))
        self.assertEqual(claims('```\nonset detection'), ([], []))
        self.assertEqual(claims('````\n```\nonset detection\n````'), ([], []))
        self.assertEqual(claims('~~~\n```\nonset detection\n~~~'), ([], []))
        self.assertEqual(claims('`onset detection`')[0], ['onset detection'])

    def test_good(self):
        self.put('README.md', 'detects onsets')
        self.put('app.py', 'import librosa\nlibrosa.onset.onset_detect(y=x)')
        self.assertEqual(self.cli()[0:2], (0, 'PASS\n'))

    def test_bad_exact(self):
        self.put('README.md', 'detects onsets')
        self.put('app.py', 'import librosa\nlibrosa.load("x")')
        code, out, _ = self.cli('--json')
        self.assertEqual(code, 2)
        result = json.loads(out)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['id'], 'documented-onset-detection-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertTrue(result['findings'][0]['message'])

    def test_test_only(self):
        self.put('README.md', 'onset detection')
        self.put('tests/check.py', 'engine.detect_onsets()')
        result = audit(self.root)
        self.assertEqual(result['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.cli()[0], 0)
        self.assertEqual(self.cli('--fail-on', 'MEDIUM')[0], 2)
        self.assertEqual(self.cli('--fail-on', 'LOW')[0], 2)

    def test_denial_exact(self):
        self.put('README.md', 'does not detect onsets')
        self.put('app.py', 'engine.detect_onsets()')
        code, out, _ = self.cli('--json')
        result = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['id'], 'documented-no-onset-detection-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')

    def test_no_claim(self):
        self.put('README.md', 'General documentation')
        self.put('app.py', 'engine.detect_onsets()')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_no_source_asymmetry(self):
        self.put('README.md', 'onset detection')
        self.assertEqual(self.cli()[0], 2)
        self.put('README.md', 'no onset detection')
        self.assertEqual(self.cli()[0], 0)

    def test_docs_and_exclusions(self):
        self.put('other.md', 'onset detection')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
        self.put('nested/docs/guide.md', 'onset detection')
        for path in ('fixtures/a.py', 'docs/a.py', 'examples/a.py', 'x/fixtures/a.py'):
            self.put(path, 'engine.detect_onsets()')
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli('--ignore', 'nested')[0], 0)
        self.assertEqual(self.cli('--ignore', 'nest')[0], 2)
        self.assertEqual(self.cli('--ignore', 'nested', '--ignore', 'examples')[0], 0)

    def test_all_test_file_forms(self):
        self.put('README.md', 'onset detection')
        for path in ('tests/a.py', 'nested/tests/a.py', 'test_engine.py', 'engine_test.py'):
            with self.subTest(path=path):
                f = self.put(path, 'engine.detect_onsets()')
                self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
                f.unlink()

    def test_symlinks(self):
        self.put('README.md', 'onset detection')
        with tempfile.TemporaryDirectory() as external:
            target = Path(external)
            (target / 'e.py').write_text('engine.detect_onsets()')
            (self.root / 'linked.py').symlink_to(target / 'e.py')
            (self.root / 'linked_dir').symlink_to(target, target_is_directory=True)
            self.assertEqual(self.cli()[0], 2)
            (target / 'claim.md').write_text('onset detection')
            (self.root / 'README.md').unlink()
            (self.root / 'README.md').symlink_to(target / 'claim.md')
            self.assertEqual(self.cli()[0], 0)

    def test_single_module(self):
        self.put('README.md', 'onset detection')
        self.put('binding.py', 'import aubio as au')
        self.put('call.py', 'au.onset()')
        self.assertEqual(self.cli()[0], 2)
        self.put('binding.py', 'import essentia as es')
        self.put('call.py', 'es.standard.OnsetDetection()')
        self.assertEqual(self.cli()[0], 2)

    def test_special_routes(self):
        sources = [
            'import librosa\nlibrosa.onset_detect()',
            'import librosa\nlibrosa.onset.onset_detect()',
            'import librosa as lr\nlr.onset.onset_detect()',
            'from librosa import onset_detect\nonset_detect()',
            'from librosa.onset import onset_detect as od\nod()',
            'import aubio\naubio.onset()',
            'import aubio as au\nau.onset()',
            'import essentia\nessentia.OnsetDetection()',
            'import essentia as es\nes.standard.OnsetDetection()',
            'import essentia as es\nes.standard.OnsetDetectionGlobal()',
            'import librosa\ndef onset_detect(): pass\nlibrosa.onset_detect()',
            'from librosa import onset_detect\ndef onset_detect(): pass\nonset_detect()',
            'import aubio\ndef onset(): pass\naubio.onset()',
            'import essentia\ndef OnsetDetection(): pass\nessentia.OnsetDetection()',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(has_evidence(source))

    def test_generic_routes(self):
        for name in GENERIC:
            for source in ('obj.' + name + '()', 'from detector import ' + name + '\n' + name + '()', 'from detector import ' + name + ' as run\nrun()'):
                with self.subTest(source=source):
                    self.assertTrue(has_evidence(source))
            self.assertFalse(has_evidence(name + '()'))
            self.assertFalse(has_evidence('def ' + name + '(): pass\nobj.' + name + '()'))
            self.assertFalse(has_evidence('class C:\n def ' + name + '(self): pass\nobj.' + name + '()'))

    def test_alias_shadow(self):
        self.assertFalse(has_evidence('from detector import detect_onsets as run\ndef run(): pass\nrun()'))
        self.assertFalse(has_evidence('from detector import detect_onsets as run\ndef detect_onsets(): pass\nrun()'))

    def test_non_evidence(self):
        sources = [
            'import librosa', 'import aubio', 'import essentia',
            'librosa.load("audio")', 'soundfile.read("audio")', 'torchaudio.load("audio")', 'wave.open("x").readframes(10)',
            'mic.listen(); mic.record(); sounddevice.rec(); stream.read()',
            'sounddevice.play(audio)', 'whisper.transcribe(audio); r.recognize_google(audio)',
            'tts.speak(text)', 'vad.is_speech(audio); get_speech_timestamps(audio)',
            'pvporcupine.create(); model.predict(audio); model.detect_keyword(audio)',
            'model.verify_files(a,b); model.verify_speaker(audio)', 'pipeline.diarize(audio)',
            'noisereduce.reduce_noise(y=x); model.suppress_noise(x); model.remove_noise(x)',
            'acoustid.fingerprint_file("x"); obj.fingerprint_audio(x)',
            'AudioTagging().inference(x); obj.detect_sound_event(x)',
            'demucs.separate(x); obj.separate_stems(x)',
            'librosa.beat.beat_track(x); aubio.tempo(); essentia.RhythmExtractor()',
            'librosa.yin(x); librosa.piptrack(x); crepe.predict(x); aubio.pitch(); obj.to_pitch()',
            'librosa.feature.chroma_cqt(x); librosa.feature.chroma_cens(x); librosa.feature.chroma_stft(x); librosa.feature.mfcc(x); essentia.Chromagram(); librosa.feature.zero_crossing_rate(x)',
            'obj.onset_envelope(x); obj.spectral_flux(x)',
            'import librosa\nlibrosa.onset.onset_strength(x)',
            'essentia.ChordsDetection(); obj.detect_chords(x)', 'essentia.KeyExtractor(); obj.detect_key(x)',
            'basic_pitch.predict(x); obj.transcribe_music(x); obj.audio_to_midi(x); obj.detect_notes(x)',
            'model.generate_audio(x)', 'GenreClassifier().predict(x); obj.classify_genre(x)',
            'InstrumentClassifier().predict(x); obj.recognize_instruments(x)',
            'MoodClassifier().predict(x); EmotionClassifier().predict(x); obj.recognize_mood(x)',
            'obj.speech_emotion(x)', 'obj.lyric_sentiment(text)', 'obj.valence(x); obj.arousal(x)',
            'obj.tag_audio(x)', 'model.predict(x); model.forward(x); obj.classify(x)',
            'pipeline("audio-classification")(x)',
            'pretty_midi.PrettyMIDI(); pretty_midi.Instrument(0); pretty_midi.Note(1,2,3,4); music21.note.Note("C")',
            'music21.stream.Stream().show(); verovio.renderToSVG(x)',
            'hashlib.md5(data); hashlib.sha256(data)', 'obj.filter(x); obj.equalize(x)',
            'obj.mix_tracks(x)', 'obj.normalize(x)', 'obj.detect_language(x)', 'obj.translate(x)',
            'wrong.onset()', 'wrong.OnsetDetection()', 'wrong.OnsetDetectionGlobal()',
            'import aubio\naubio.other.onset()',
            'subprocess.run(["onset-detector", "audio.wav"])',
            's = "librosa.onset.onset_detect()"', 'obj.detect_onsets',
            'obj.detect_onsets(\nsyntax error',
            'def run():\n import aubio\n aubio.onset()',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(has_evidence(source))
        # A wrong-library base fails the library route, but this spelling is
        # explicitly admitted by the generic route with any base.
        self.assertTrue(has_evidence('wrong.onset_detect()'))
        self.assertFalse(has_evidence('def onset_detect(): pass\nwrong.onset_detect()'))

    def test_errors(self):
        for args in ([], ['--unknown'], [str(self.root), '--fail-on', 'INVALID'], [str(self.root / 'missing')]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    code = main(args)
                except SystemExit as exc:
                    code = exc.code
                self.assertEqual(code, 1)
        f = self.put('README.md', 'x')
        f.chmod(0)
        self.addCleanup(f.chmod, 0o644)
        self.assertEqual(self.cli()[0], 1)

    def test_verbose_json(self):
        self.put('README.md', 'onset detection')
        self.assertIn('claims', self.cli('--verbose')[1])
        self.assertIn('evidence', json.loads(self.cli('--json')[1]))

    def test_version_and_module(self):
        self.assertEqual(__version__, '0.1.0')
        run = subprocess.run([sys.executable, '-m', 'onset_detection_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout.strip()), (0, '0.1.0'))
        run = subprocess.run([sys.executable, '-m', 'onset_detection_claim_audit', str(self.root)], capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout.strip()), (0, 'PASS'))

    def test_console_entry_point(self):
        # Exercise the configured console target through the same wrapper an
        # installer generates. Fresh-distribution probes also verify pip's
        # actual generated scripts outside the checkout.
        project = Path(__file__).resolve().parents[1]
        config = (project / 'pyproject.toml').read_text()
        self.assertIn('onset-detection-claim-audit = "onset_detection_claim_audit.audit:main"', config)
        wrapper = self.put('onset-detection-claim-audit',
                           'from onset_detection_claim_audit.audit import main\n'
                           'raise SystemExit(main())\n')
        import os
        env = dict(os.environ, PYTHONPATH=str(project))
        for args, expected in ((['--version'], '0.1.0'), ([str(self.root)], 'PASS')):
            result = subprocess.run([sys.executable, str(wrapper)] + args,
                                    cwd=str(self.root), env=env,
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, expected))

    def test_readme_self_audit(self):
        project = Path(__file__).resolve().parents[1]
        self.assertEqual(claims((project / 'README.md').read_text()), ([], []))
        self.assertEqual(audit(project)['verdict'], 'PASS')


if __name__ == '__main__':
    unittest.main()
