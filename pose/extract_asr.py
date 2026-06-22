"""
나레이션 ASR — faster-whisper로 설명영상 음성을 한국어 전사 + 구간 타임스탬프.

입력 : 오디오 wav (results/_audio/*.wav)
출력 : asr.json (segment별 text + start/end + 단어 타임스탬프)
용도 : 단계 자동분할(segment.py) 경계에 "무슨 작업인지" 의미 라벨을 붙이는 멀티모달 신호.

usage:
  python pose/extract_asr.py --audio results/_audio/front_explain_90s.wav \
      --out-json results/seg_test/asr.json --model small
"""
import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3")
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--prompt", default=None,
                    help="도메인 어휘 주입(initial_prompt) — 전문용어 인식률↑")
    args = ap.parse_args()

    # 공정관리지침서 GMT-QI-700-4 부품·공정 용어 (기본 도메인 프롬프트)
    default_prompt = ("체크밸브 조립. 부품: 디스크(DISC), 스페이서(SPACER), 힌지핀(HINGE PIN), "
                      "토션 스프링, 가이드(GUIDE), 바디(BODY), 세트 스크류. "
                      "공정: 정렬, 삽입, 체결, 검사.")
    prompt = args.prompt or default_prompt

    print(f"[info] model={args.model} lang={args.lang} (CPU int8) | 도메인프롬프트 ON")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        args.audio, language=args.lang, word_timestamps=True, vad_filter=True,
        initial_prompt=prompt,
    )

    out = []
    for s in segments:
        seg = {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
               "words": [{"w": w.word, "t": round(w.start, 2)} for w in (s.words or [])]}
        out.append(seg)
        print(f"  [{s.start:6.1f}~{s.end:6.1f}] {s.text.strip()}")

    Path(args.out_json).write_text(
        json.dumps({"audio": args.audio, "lang": args.lang, "model": args.model,
                    "duration": round(info.duration, 1), "segments": out},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {len(out)} narration segments -> {args.out_json}")


if __name__ == "__main__":
    main()
