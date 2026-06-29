"""테스팅B: 로컬 VLM(SmolVLM2-2.2B)로 섹터 프레임→공정단계 분류. DINOv2(50%천장)와 비교."""
import csv, json
from pathlib import Path
import torch, cv2
from label_superlabel import VIDEO_PATHS, SUPER, gt_map

LABELS = ["공정8(DISC·SPACER·HINGE PIN 조립)","공정9(GUIDE 결합)","공정10(BODY-GUIDE 결합)","공정11(SET SCREW 결합)"]
PROMPT = ("This is a check-valve assembly step. Which ONE process is shown? Answer ONLY the number.\n"
          "8 = assembling disc/spacer/hinge pin (inserting pin, aligning spring)\n"
          "9 = attaching GUIDE parts to both sides\n"
          "10 = inserting the assembly into the BODY\n"
          "11 = fastening SET SCREW / bolt with a wrench\n"
          "Answer (8/9/10/11):")

def main():
    from transformers import AutoProcessor, AutoModelForImageTextToText
    mid="HuggingFaceTB/SmolVLM2-2.2B-Instruct"
    proc=AutoProcessor.from_pretrained(mid)
    model=AutoModelForImageTextToText.from_pretrained(mid, torch_dtype=torch.float32)
    dev="mps" if torch.backends.mps.is_available() else "cpu"; model.to(dev).eval()
    gt=gt_map("data/ground_truth.csv"); root=Path(".")
    num2lab={"8":LABELS[0],"9":LABELS[1],"10":LABELS[2],"11":LABELS[3]}
    print("=== 테스팅B: 로컬 VLM(SmolVLM2) 공정5 라벨 ===")
    agg={}
    for tgt in [v for v in VIDEO_PATHS if v in gt]:
        cap=cv2.VideoCapture(str(root/VIDEO_PATHS[tgt])); fps=cap.get(cv2.CAP_PROP_FPS) or 30
        hit=tot=0
        for r in gt[tgt]:
            t=(float(r["t_start"])+float(r["t_end"]))/2
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(t*fps)); ok,fr=cap.read()
            if not ok: continue
            fr=cv2.cvtColor(fr,cv2.COLOR_BGR2RGB)
            from PIL import Image
            msgs=[{"role":"user","content":[{"type":"image"},{"type":"text","text":PROMPT}]}]
            inp=proc.apply_chat_template(msgs,add_generation_prompt=True,tokenize=True,
                return_dict=True,return_tensors="pt",images=[Image.fromarray(fr)]).to(dev)
            with torch.no_grad():
                out=model.generate(**inp,max_new_tokens=6,do_sample=False)
            ans=proc.batch_decode(out[:,inp["input_ids"].shape[1]:],skip_special_tokens=True)[0]
            import re; m=re.search(r'(8|9|10|11)',ans)
            pred=num2lab.get(m.group(1)) if m else None
            truth=SUPER[r["표준단계"]]
            tot+=1; hit+=(pred==truth)
        cap.release()
        acc=hit/tot*100 if tot else 0
        print(f"  [{tgt:10} 공정5 VLM] {hit}/{tot} = {acc:.0f}%"); agg[tgt]=acc
    import numpy as np
    print(f"  평균: {np.mean(list(agg.values())):.0f}% (DINOv2 공정5 50% 대비)")

if __name__=="__main__": main()
