#!/usr/bin/env python3
"""Validate S83's frozen release metadata and map each selected sound ID to its runtime path."""
import argparse
import json
import re
from pathlib import Path, PurePosixPath

EXPECTED_REPO = "agmmltd-arch/agmm-video-render"
EXPECTED_RELEASE = 403141125
EXPECTED_TAG = "S83-protected-inputs-20261004"
EXPECTED_TARGET = "d75f21511e9603506f9cc934a0f430db6d75d172"
EXPECTED_PRIVATE_COMMIT = "04b48f467025d86ffcdb54d933717682b0e84903"
EXPECTED_GIT_BLOBS = {
    'protected-inputs/S83/sound/library/foley_click/foley_click_01.wav': 'c31ec9811e7051b51a85d019c512619698fd0bf2',
    'protected-inputs/S83/sound/library/foley_click/foley_click_02.wav': '0b7386f0de62c29ab547129dd65441eadaae0bd8',
    'protected-inputs/S83/sound/library/foley_click/foley_click_04.wav': 'e2ea78ea2d623511376b600470c7fa378bf7c326',
    'protected-inputs/S83/sound/library/foley_click/foley_click_05.wav': '41e44c3c05be7e7edc01df64b91f78e5ac17dd82',
    'protected-inputs/S83/sound/library/foley_click/foley_click_06.wav': '008db77c1eed016b442479e3516957777ac500e2',
    'protected-inputs/S83/sound/library/foley_paper/foley_paper_02.wav': 'a3af4a65c9bef4e9a02bb5058052c56f625540ad',
    'protected-inputs/S83/sound/library/foley_paper/foley_paper_03.wav': '5c8d101eeb55c0b62633f0d9fe11bd2611099be7',
    'protected-inputs/S83/sound/library/foley_paper/foley_paper_05.wav': '48a3eff0f37e410bad159a23fc78c8b5b59c19f9',
    'protected-inputs/S83/sound/library/foley_paper/foley_paper_08.wav': '0d35908af7782211a262dbafd71479f0368d54fb',
    'protected-inputs/S83/sound/library/foley_paper/foley_paper_09.wav': 'd9380d8965524ba17bc45c747bda980f92b4ee3c',
    'protected-inputs/S83/sound/library/foley_stamp/foley_stamp_01.wav': 'b79b083ac43094cd688c3c05612514506ebea216',
    'protected-inputs/S83/sound/library/foley_stamp/foley_stamp_03.wav': '70330c99f8bf5fbed31ebb7c545fe1736030292b',
    'protected-inputs/S83/sound/library/impact_soft/impact_soft_09.wav': 'da912b5642fcda531d87c18e639482c2818e8cec',
    'protected-inputs/S83/sound/library/paper_page/paper_page_06.wav': '6651dbb2c9c802c7cc8bff358c5f22a83c3ee4ae',
    'protected-inputs/S83/sound/library/paper_page/paper_page_07.wav': 'a64c026a69bfb268294b0db982009b87ea2541b3',
    'protected-inputs/S83/sound/library/paper_page/paper_page_08.wav': '95913f4b9c94842f39ce7bd17fac9fdb5e8ed14e',
    'protected-inputs/S83/sound/library/paper_page/paper_page_10.wav': '818b86ff57cd4439287eca157b305301d97f61b1',
    'protected-inputs/S83/voice/S83.wav': '10c3a4f72fa017af3de8833dd3b5fd4a78b805ac',
}
EXPECTED_SFX = {
    'foley_click_01.wav': (610332048, 'foley_click_01', 'inputs/sound/library/foley_click/foley_click_01.wav', 29472, 'sha256:2a63dc6bff2514a0de47177788184956094fd80037d66a4876e50751f109253e'),
    'foley_click_02.wav': (610331993, 'foley_click_02', 'inputs/sound/library/foley_click/foley_click_02.wav', 7014, 'sha256:3b321ace83be2de6ea20bace72003061de5c6475eb40787ed64bdca9edb3a1a7'),
    'foley_click_04.wav': (610331996, 'foley_click_04', 'inputs/sound/library/foley_click/foley_click_04.wav', 7014, 'sha256:f960975cd2173626a33a7a885f32f8322d478f58a7bb40cf238f4a272bf35399'),
    'foley_click_05.wav': (610332062, 'foley_click_05', 'inputs/sound/library/foley_click/foley_click_05.wav', 72102, 'sha256:23da61200a62daa38ea6503a00c616b8569621efa5131d22e9e15389aea85c76'),
    'foley_click_06.wav': (610332049, 'foley_click_06', 'inputs/sound/library/foley_click/foley_click_06.wav', 43302, 'sha256:3f7d291ed86b364ffbd4f2dcef2d8b5ebca46e579bfcd5b83e2b3ea4cad36478'),
    'foley_paper_02.wav': (610332019, 'foley_paper_02', 'inputs/sound/library/foley_paper/foley_paper_02.wav', 35814, 'sha256:f1e1a0d561a0039e6999944c773f6b6eac321649aff5304c5ead7e682191fa1b'),
    'foley_paper_03.wav': (610331992, 'foley_paper_03', 'inputs/sound/library/foley_paper/foley_paper_03.wav', 86502, 'sha256:97966ae2339209e47587ecfefab354a3eaa0b09f620bb054cfa1d9f7a7d04805'),
    'foley_paper_05.wav': (610332024, 'foley_paper_05', 'inputs/sound/library/foley_paper/foley_paper_05.wav', 79590, 'sha256:49f23be34ff0ec254703b5fd7e91ccb17ae735bfee9f60efc10b8c9e46cbf21c'),
    'foley_paper_08.wav': (610332047, 'foley_paper_08', 'inputs/sound/library/foley_paper/foley_paper_08.wav', 82470, 'sha256:adea920a80b13099e98652b0df27d503a4f788f0a5a820b21250d39451b1d83d'),
    'foley_paper_09.wav': (610332059, 'foley_paper_09', 'inputs/sound/library/foley_paper/foley_paper_09.wav', 130278, 'sha256:67672135813826b43f1e8154b22644875716677e54556c00e849d6f1eb0244c0'),
    'foley_stamp_01.wav': (610332023, 'foley_stamp_01', 'inputs/sound/library/foley_stamp/foley_stamp_01.wav', 100902, 'sha256:1c401c3e5db7161c1bf034b2f6864d957af08ba6d47a861da01fb35128480194'),
    'foley_stamp_03.wav': (610332056, 'foley_stamp_03', 'inputs/sound/library/foley_stamp/foley_stamp_03.wav', 100902, 'sha256:31bc9a8ac5d2b3560c7e087079cb60c5470d161f1cf990ccf44952a8767f7103'),
    'impact_soft_09.wav': (610331991, 'impact_soft_09', 'inputs/sound/library/impact_soft/impact_soft_09.wav', 42332, 'sha256:725d5563ef95268cb1b1a9e0bbd83c56416aa3cbbcc5a6f5c2a90d5d5f3afb60'),
    'paper_page_06.wav': (610332029, 'paper_page_06', 'inputs/sound/library/paper_page/paper_page_06.wav', 27244, 'sha256:42a68a895a5fd14d0ef1df9b21e46c9f77fdbc6aea243e18ae22928cf6eb82f1'),
    'paper_page_07.wav': (610332052, 'paper_page_07', 'inputs/sound/library/paper_page/paper_page_07.wav', 223770, 'sha256:ff38a07ef3489a2e4c90e33cdb4ea7cb398dff167cbb0288226c704ee6f0d51f'),
    'paper_page_08.wav': (610332051, 'paper_page_08', 'inputs/sound/library/paper_page/paper_page_08.wav', 163736, 'sha256:083e21e28e0ceea960351ce5cf7e54621012fad6f15b6ec12a1d1fca53ad3fc4'),
    'paper_page_10.wav': (610332060, 'paper_page_10', 'inputs/sound/library/paper_page/paper_page_10.wav', 97128, 'sha256:6170388a02a15f7d0dae6a78ca832e44a577c60f21c55840999552df8e432dc5'),
}
VOICE = {"id": 610331997, "name": "S83.wav", "size": 2713200,
         "digest": "sha256:09d63637253f35155c74e183ba32fb530e10261218a607dfb5544ad829138cb6",
         "runtime_path": "inputs/S83.wav", "private_tree_path": "protected-inputs/S83/voice/S83.wav", "private_tree_commit": EXPECTED_PRIVATE_COMMIT, "git_blob_sha": "10c3a4f72fa017af3de8833dd3b5fd4a78b805ac", "sfx_id": None}


def validate(d):
    if d.get("private_tree_binding", {}).get("commit") != EXPECTED_PRIVATE_COMMIT:
        raise ValueError("private Git tree commit mismatch")
    if d.get("schema") != "agmm-s83-protected-inputs-v1":
        raise ValueError("unsupported protected-input manifest schema")
    if (d.get("repository"), d.get("release_id"), d.get("tag"), d.get("target_commitish")) != (EXPECTED_REPO, EXPECTED_RELEASE, EXPECTED_TAG, EXPECTED_TARGET):
        raise ValueError("protected release identity mismatch")
    assets = d.get("assets")
    if not isinstance(assets, list) or len(assets) != 18:
        raise ValueError("exact 18-file allowlist required")
    by_name = {a.get("name"): a for a in assets}
    if len(by_name) != 18 or set(by_name) != set(EXPECTED_SFX) | {"S83.wav"}:
        raise ValueError("asset names are not the exact voice plus 17 selected SFX")
    seen_ids, seen_paths = set(), set()
    voice = by_name["S83.wav"]
    for key, value in VOICE.items():
        if voice.get(key) != value: raise ValueError("selected voice native binding mismatch")
    for name, (asset_id, sfx_id, runtime_path, size, digest) in EXPECTED_SFX.items():
        row = by_name[name]
        expected_private_path = "protected-inputs/S83/sound/library/" + runtime_path.split("/library/", 1)[1]
        if (row.get("id"), row.get("sfx_id"), row.get("runtime_path"), row.get("private_tree_path"), row.get("size"), row.get("digest"), row.get("private_tree_commit")) != (asset_id, sfx_id, runtime_path, expected_private_path, size, digest, EXPECTED_PRIVATE_COMMIT):
            raise ValueError("selected SFX runtime binding mismatch: " + name)
    for row in assets:
        if EXPECTED_GIT_BLOBS.get(row.get("private_tree_path")) != row.get("git_blob_sha"):
            raise ValueError("private Git blob binding mismatch: " + str(row.get("name")))
        if row.get("private_tree_commit") != EXPECTED_PRIVATE_COMMIT:
            raise ValueError("private Git commit binding mismatch: " + str(row.get("name")))
        if not re.fullmatch(r"[0-9a-f]{40}", str(row.get("git_blob_sha", ""))):
            raise ValueError("invalid native Git blob SHA: " + str(row.get("name")))
        if row.get("id") in seen_ids or row.get("runtime_path") in seen_paths:
            raise ValueError("duplicate asset id or runtime destination")
        seen_ids.add(row["id"]); seen_paths.add(row["runtime_path"])
        if not isinstance(row.get("size"), int) or row["size"] <= 0:
            raise ValueError("invalid protected asset byte size")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(row.get("digest", ""))):
            raise ValueError("invalid protected asset digest")
        p = PurePosixPath(row["runtime_path"])
        private = PurePosixPath(row["private_tree_path"])
        if (p.is_absolute() or ".." in p.parts or not p.parts or str(p) != row["runtime_path"]
                or private.is_absolute() or ".." in private.parts or not private.parts or str(private) != row["private_tree_path"]):
            raise ValueError("unsafe runtime path")
    return assets


def main():
    p=argparse.ArgumentParser(); p.add_argument("manifest", type=Path); a=p.parse_args()
    assets=validate(json.loads(a.manifest.read_text()))
    print(f"PROTECTED_INPUT_MANIFEST_VALID release={EXPECTED_RELEASE} assets={len(assets)}")

if __name__=="__main__": main()
