"""
sopgen — self-contained demo: video keypoints -> 표준 작업 지도서 (Phases 0-4).

Stages: clip_profile (A) -> signal_digest (B) -> keyframe_sampler (C) ->
step_author (E, RAG/Claude) -> assembler (F) -> render (H), with a SQLite RAG
store (Phase 3), a standard-time estimate (Phase 2), and a local web UI (Phase 4).
Run:  python -m sopgen.pipeline --stem <clip>      |   python -m sopgen.app
"""
