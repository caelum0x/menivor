# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pixelle-Video Pipelines

Video generation pipelines with different strategies and workflows.
Each pipeline implements a specific video generation approach.
"""

__all__ = [
    "BasePipeline",
    "LinearVideoPipeline",
    "PipelineContext",
    "StandardPipeline",
    "CustomPipeline",
    "AssetBasedPipeline",
]


def __getattr__(name: str):
    """Keep historical exports without importing every GPU dependency at startup.

    The product runtime imports its policy from this package before model
    execution.  Eagerly importing the historical pipelines would pull optional
    ffmpeg/torch services into the API process merely to inspect a capability.
    """
    if name == "BasePipeline":
        from pipelines.base import BasePipeline

        return BasePipeline
    if name in {"LinearVideoPipeline", "PipelineContext"}:
        from pipelines.linear import LinearVideoPipeline, PipelineContext

        return {"LinearVideoPipeline": LinearVideoPipeline, "PipelineContext": PipelineContext}[name]
    if name == "StandardPipeline":
        from pipelines.standard import StandardPipeline

        return StandardPipeline
    if name == "CustomPipeline":
        from pipelines.custom import CustomPipeline

        return CustomPipeline
    if name == "AssetBasedPipeline":
        from pipelines.asset_based import AssetBasedPipeline

        return AssetBasedPipeline
    raise AttributeError(name)
