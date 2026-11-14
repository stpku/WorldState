"""Synthetic checks for source-bound floor conflict diagnostics, not accuracy."""
from __future__ import annotations

import copy
import hashlib

import pytest

np = pytest.importorskip('numpy')
cv2 = pytest.importorskip('cv2')
pytest.importorskip('pycolmap')

from products.worldstate_bim.floor_semantic_review import review_floor_tracks
from products.worldstate_bim.semantic_vision import UperNetOnnxProvider


class FakeSession:
    def __init__(self):
        self.calls = 0

    def run(self, _, feed):
        self.calls += 1
        # Dark and light source fixtures represent different local predictions;
        # these are synthetic behavior checks, not a vision-model evaluation.
        label = 75 if float(feed['pixel_values'].mean()) < 0 else 3
        logits = np.zeros((1, 150, 128, 128), dtype=np.float32)
        logits[0, label, :, :] = 12
        return [logits]


class FakeProvider:
    def __init__(self):
        self.session = FakeSession()


def fixture_fusion(tmp_path):
    cameras = []; track_observations = {1: [], 2: []}
    for image_id, (value, track_id) in enumerate(((0,1), (0,1), (255,2), (255,2)), 1):
        name = f'photo-{image_id}.png'; path = tmp_path/name
        assert cv2.imwrite(str(path), np.full((80, 100, 3), value, dtype=np.uint8))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        cameras.append({'image_id': image_id, 'photo': name, 'sha256': sha, 'width_px': 100, 'height_px': 80})
        track_observations[track_id].append({'image_id': image_id, 'photo': name, 'photo_sha256': sha,
            'pixel_xy': [50., 40.], 'semantic_class': 3, 'usable': True, 'model_score_uncalibrated': .6})
    tracks = [{'id': i, 'status': 'SUPPORTED', 'semantic_class': 3, 'xyz': [float(i), 0., 0.],
               'observations': track_observations[i]} for i in (1,2)]
    return {'schema': 'worldstate-multiview-semantic-fusion/0.1', 'model_sha256': UperNetOnnxProvider.MODEL_SHA256,
            'semantic_manifest_sha256': 'a'*64, 'source_reconstruction': [], 'cameras': cameras, 'tracks': tracks,
            'floor_planes': [{'support_point_ids': [1,2]}]}


def test_two_view_disagreement_is_a_review_request_and_never_mutates_fusion(tmp_path):
    fusion = fixture_fusion(tmp_path); original = copy.deepcopy(fusion); provider = FakeProvider()
    result = review_floor_tracks(fusion, tmp_path, provider)
    assert fusion == original
    assert result['disputed_track_ids'] == [1]
    assert result['track_reviews'][0]['status'] == 'MULTIVIEW_CROP_DISAGREEMENT_REVIEW_REQUIRED'
    assert result['track_reviews'][1]['status'] == 'NO_CROP_DISAGREEMENT_NOT_VERIFIED'
    assert [o['local_crop']['class_id'] for o in result['track_reviews'][0]['observations']] == [75,75]
    assert result['counterfactual_excluding_disputed_tracks']['status'] == 'HYPOTHETICAL_NOT_A_CONFIRMED_CORRECTION'
    assert provider.session.calls == 4


def test_image_tampering_is_rejected_before_inference(tmp_path):
    fusion = fixture_fusion(tmp_path); provider = FakeProvider()
    (tmp_path/'photo-1.png').write_bytes(b'changed source image')
    with pytest.raises(ValueError, match='hash mismatch'):
        review_floor_tracks(fusion, tmp_path, provider)
    assert provider.session.calls == 0


def test_review_limit_reports_unreviewed_floor_support(tmp_path):
    fusion = fixture_fusion(tmp_path); provider = FakeProvider()
    result = review_floor_tracks(fusion, tmp_path, provider, max_tracks=1)
    assert result['reviewed_track_count'] == 1
    assert result['unreviewed_support_track_ids'] == [2]
    assert result['counterfactual_excluding_disputed_tracks']['unreviewed_floor_track_ids'] == [2]
    assert provider.session.calls == 2


def test_disputed_track_quarantines_unreviewed_duplicate_evidence(tmp_path):
    fusion = fixture_fusion(tmp_path); duplicate = copy.deepcopy(fusion['tracks'][0]); duplicate['id'] = 3
    fusion['tracks'].append(duplicate); fusion['floor_planes'][0]['support_point_ids'].append(3)
    result = review_floor_tracks(fusion, tmp_path, FakeProvider(), max_tracks=1)
    assert result['disputed_track_ids'] == [1]
    assert result['quarantined_track_ids_including_duplicates'] == [1,3]
    assert result['unreviewed_support_track_ids'] == [2]
    assert result['support_duplicate_groups'][0]['redundant_track_ids'] == [3]
    assert result['counterfactual_excluding_disputed_tracks']['distinct_tracks_after_quarantine'] == 1


def test_missing_floor_still_offers_supported_tracks_for_review(tmp_path):
    fusion = fixture_fusion(tmp_path); fusion['floor_planes'] = []
    result = review_floor_tracks(fusion, tmp_path, FakeProvider())
    assert result['review_scope'] == 'SUPPORTED_FLOOR_TRACKS_WITHOUT_A_FITTED_PLANE'
    assert result['reviewed_track_count'] == 2 and result['disputed_track_ids'] == [1]
