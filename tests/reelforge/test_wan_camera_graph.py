"""Pure Wan camera-control graph builder — no I/O, deterministic injection.

Asserts the four gotcha guards (pose translation, legal-length snap kept in
agreement across node131/node135, base_resolution snap, omitted optionals) plus
the tolerant output resolver, all against the pinned API-format asset.
"""

from __future__ import annotations

from app.services.render.backends import _wan_camera_graph as g


def _request(num_frames: int = 81, pose: str = "Pan Right") -> dict:
    return {
        "capability": "image_to_video",
        "prompt": "hero product shot",
        "negative_prompt": "blurry, low quality",
        "start_image_url": "https://cdn/start.png",
        "num_frames": num_frames,
        "camera": {
            "camera_pose": pose,
            "speed": 2,
            "width": 832,
            "height": 480,
            "length": num_frames,
            "fx": 0.61,
            "fy": 0.72,
            "cx": 0.5,
            "cy": 0.5,
        },
    }


def test_template_loads_flat_api_format_with_string_ids():
    tpl = g.load_template()
    assert set(["100", "121", "122", "131", "130", "134", "135", "106"]).issubset(tpl)
    # API format: each node has class_type + inputs.
    assert tpl["135"]["class_type"] == "Wan2_2FunV2VSampler"
    assert tpl["106"]["class_type"] == "VHS_VideoCombine"
    # Edges are [from_node_id, from_slot] refs.
    assert tpl["135"]["inputs"]["start_image"] == ["100", 0]
    assert tpl["135"]["inputs"]["camera_conditions"] == ["130", 0]
    assert tpl["130"]["inputs"]["camera_pose"] == ["131", 0]


def test_pinned_sampler_dropped_phantom_fixed_widget():
    # The 'fixed' control_after_generate widget must NOT appear; steps/cfg keep
    # their real values (not shifted by one).
    inp = g.load_template()["135"]["inputs"]
    assert "fixed" not in inp.values()
    assert inp["seed"] == 43
    assert inp["steps"] == 50
    assert inp["cfg"] == 6.0
    assert inp["scheduler"] == "Flow"


def test_optional_sampler_inputs_absent():
    inp = g.load_template()["135"]["inputs"]
    for optional in ("validation_video", "control_video", "end_image", "ref_image", "riflex_k"):
        assert optional not in inp


def test_build_graph_injects_image_prompt_and_pose():
    graph = g.build_graph(_request(), {"name": "up.png", "subfolder": ""})
    assert graph["100"]["inputs"]["image"] == "up.png"
    assert graph["121"]["inputs"]["prompt"] == "hero product shot"
    assert graph["122"]["inputs"]["prompt"] == "blurry, low quality"
    combine = graph["131"]["inputs"]
    assert combine["camera_pose1"] == "Pan Right"
    assert combine["camera_pose2"] == "Static"
    assert combine["camera_pose3"] == "Static"
    assert combine["camera_pose4"] == "Static"
    assert combine["speed"] == 2


def test_build_graph_does_not_mutate_template():
    before = g.load_template()["121"]["inputs"]["prompt"]
    g.build_graph(_request(), {"name": "up.png"})
    assert g.load_template()["121"]["inputs"]["prompt"] == before


def test_pose_translation_clockwise_and_anti_clockwise():
    assert g.translate_pose("ClockWise") == "CW"
    assert g.translate_pose("Anti Clockwise") == "ACW"
    assert g.translate_pose("Pan Left") == "Pan Left"
    graph = g.build_graph(_request(pose="ClockWise"), None)
    assert graph["131"]["inputs"]["camera_pose1"] == "CW"


def test_length_snapped_and_identical_across_nodes():
    # 80 is illegal (not k*4+1); snaps to 81 and must match on 131 + 135.
    graph = g.build_graph(_request(num_frames=80), None)
    assert graph["131"]["inputs"]["video_length"] == 81
    assert graph["135"]["inputs"]["video_length"] == 81
    assert g.snap_length(80) == 81
    assert g.snap_length(81) == 81
    assert g.snap_length(3) == 5  # floor at the minimum legal length


def test_intrinsics_injected():
    graph = g.build_graph(_request(), None)
    traj = graph["130"]["inputs"]
    assert traj["fx"] == 0.61
    assert traj["fy"] == 0.72
    assert traj["cx"] == 0.5
    assert traj["cy"] == 0.5


def test_base_resolution_snapped_to_supported_bucket():
    graph = g.build_graph(_request(), None)
    # mean(832, 480) == 656 -> nearest supported bucket is 640.
    assert graph["135"]["inputs"]["base_resolution"] == 640
    assert g.snap_base_resolution(1024, 1024) == 1024
    assert g.snap_base_resolution(500, 500) == 512


def test_resolve_output_tolerant_of_list_keys():
    outputs = {"106": {"gifs": [{"filename": "Fun_00001.mp4", "subfolder": "s", "type": "output"}]}}
    ref = g.resolve_output(outputs)
    assert ref == {"filename": "Fun_00001.mp4", "subfolder": "s", "type": "output"}


def test_resolve_output_videos_key():
    outputs = {"106": {"videos": [{"filename": "out.mp4", "type": "output"}]}}
    ref = g.resolve_output(outputs)
    assert ref["filename"] == "out.mp4"
    assert ref["subfolder"] == ""


def test_resolve_output_none_when_empty():
    assert g.resolve_output({}) is None
    assert g.resolve_output({"106": {}}) is None
