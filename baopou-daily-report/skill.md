---
name: baopou-daily-report
description: 寶舖建設集團開發部「每日工作日報」填寫 skill。使用時機：使用者提到「填日報」、「寫日報」、「今天的三件事」、「日報表」、「幫我整理今天的工作」、「今天做了什麼」、「明天要做什麼」、「交日報」，即使沒明確說「使用 skill」也要觸發。本 skill 引導開發部成員逐一說出今日與明日最重要三件事，確保每件事都涵蓋人事時（需要誰配合、做了什麼結論、何時完成），並驗證今日結果有結論而非只描述行動，最後產出格式化的 .docx 日報檔。本 skill 不涵蓋簽呈製作（用 baopou-petition）、都更案開發評估（用 property-eval）、Asana 任務建立。
---

# 寶舖建設 — 每日工作日報 Skill

> 適用：寶舖建設集團開發部全體成員
> 產出：當日 .docx 日報，存至 `/Users/zhuangyinglin/Documents/Claude/Projects/開發部日報/`

---

## 流程總覽

| Step | 動作 |
|------|------|
| 0 | 確認日期與填報人 |
| 1 | 逐一收集今日三件事（含驗證） |
| 2 | 逐一收集明日三件事 |
| 3 | 產出 .docx 日報 |

---

## Step 0：基本資訊

詢問（若對話中已知則免問）：
- 今天日期（民國年月日）
- 填報人姓名

---

## Step 1：今日最重要三件事

**逐一收集，每件事詢問順序：**

1. **哪個專案？**（羅斯795、信義364、復興632…或其他）
2. **今天這件事推進到哪了？結果是什麼？**
3. **需要誰配合？**（沒有配合對象可跳過）
4. **何時前完成？**
5. **進度？**（完成 / 進行中 / 延後）
6. **有什麼需要主管知道的？**（沒有可跳過）

---

### ⚠️ 驗證規則（核心）

收到使用者的答案後，先對照以下規則驗證，有問題才追問，沒問題直接繼續：

**規則 A：今日結果要有結論，不能只描述行動**

觸發條件：今日結果只說了「做了什麼」，沒有說「得到什麼結論或結果」。

常見錯誤：
- 「與廠商開會」→ 追問：「開完會的結論是什麼？有達成什麼決議嗎？」
- 「整理資料」→ 追問：「整理出來的結果或結論是什麼？」
- 「討論 X 方案」→ 追問：「討論後的方向或判斷是什麼？」

正確示範：
- 「完成耐震初評2家議價，確認合約補充條款」
- 「初步評估案件可行，論述核心聚焦住戶前後價值計算」
- 「比較元創（B6，反計容積問題）與兆碩（B4，已解），完成三筆基地提案資料」

**規則 B：進行中要說目前到哪了**

觸發條件：進度勾「進行中」但沒有說明目前完成哪些、還剩什麼。

追問：「目前完成了哪些部分？還剩什麼沒做？」

**規則 C：延後要說延到何時**

觸發條件：進度勾「延後」但沒有說新的時間點。

追問：「延到什麼時候？」

**規則 D：需主管知道要說清楚要做什麼**

觸發條件：有填「需主管知道」但內容只是描述狀況，沒有說主管需要做什麼動作或決策。

追問：「主管需要做什麼具體的事？什麼時候需要回應？」

---

### 收集完三件事後的整理

三件事都收集完畢後，統一整理呈現給使用者確認，格式如下：

```
【今日三件事確認】

第1件事｜專案：___
今日結果：___
需要誰配合：___　何時前完成：___
進度：___
需主管知道：___（無則略）

第2件事｜…
第3件事｜…
```

若使用者確認無誤，進入 Step 2。

---

## Step 2：明日最重要三件事

**逐一收集，每件事詢問順序：**

1. **哪個專案？**
2. **明天結束時，這件事要到什麼具體狀態？**
3. **需要誰配合？**
4. **何時前完成？**

### 驗證規則

**規則 E：明日目標要是結果，不是行程**

觸發條件：明日目標只說「要去做 X」，沒有說「做完後要到什麼狀態」。

常見錯誤：
- 「明天繼續整理資料」→ 追問：「整理完後要達到什麼狀態？」
- 「明天和 X 開會」→ 追問：「這個會議結束後，你希望得到什麼結果？」

收集完三件事後同樣整理確認。

---

## Step 3：產出 .docx 日報

確認今日與明日三件事都無誤後，用以下 Python 程式碼產出 docx：

```python
# 用 python-docx 依照最終版範本格式產出
# 存檔路徑：/Users/zhuangyinglin/Documents/Claude/Projects/開發部日報/
# 檔名格式：{民國年月日}-開發部-日報-{填報人}.docx
# 例：20260511-開發部-日報-莊穎霖.docx
```

**產出規則：**
- 日期欄填民國年月日（例：115 年 5 月 11 日）
- 第1件事標題列加「（最重要）」
- 進度欄依使用者回答勾選（■完成 / ■進行中 / ■延後）
- 「需主管知道」有內容才填，沒有則顯示灰字「（沒事留空）」
- 「說明」欄：完成→顯示範本提示灰字；進行中→填入使用者說的進度說明；延後→填入新時間點
- 配合欄若無配合對象，顯示空白（不填任何提示文字）

產出後告知存檔路徑，並附上一句快速摘要（今日完成幾件、進行中幾件、明日關鍵事項是什麼）。

---

## 對話語氣原則

- 一次只問一件事，不要一次列出所有問題
- 驗證時直接追問，不要解釋為什麼要追問
- 使用者說完一件事，先整理複述再問下一件
- 全程用中文，語氣簡潔直接

---

## 範例對話節錄

```
Skill：今天第1件事，哪個專案、做了什麼結果？

使用者：羅斯795，跟建築師開會討論B1車道的問題。

Skill：開完會的結論是什麼？有決議出方案嗎？

使用者：比較了兩個方案，元創B6有反計容積問題，兆碩B4解決了，但樓上平面還沒確認。

Skill：好。需要誰配合、何時完成、進度呢？

使用者：配合元創兆碩，今天完成了。

Skill：
第1件事｜專案：羅斯795
今日結果：比較元創（B6，有反計容積問題）與兆碩（B4，反計容積已解，樓上平面待確認）
需要誰配合：元創、兆碩建築師　何時前完成：今日
進度：完成
這樣對嗎？有需要主管知道的事嗎？
```

---

## 產出程式碼模板

產出 docx 時使用以下完整範本程式碼（`today_data` 與 `tmrw_data` 由對話收集填入）：

```python
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os

# today_data = [
#   {"project": "專案名", "result": "今日結果", "partner": "配合人",
#    "deadline": "時限", "status": "完成|進行中|延後",
#    "note": "需主管知道（空字串=無）", "status_desc": "進度說明（空字串=無）"},
#   ...
# ]
# tmrw_data = [
#   {"project": "專案名", "goal": "明日目標", "partner": "配合人", "deadline": "時限"},
#   ...
# ]

def build_report(date_str, name, today_data, tmrw_data, out_dir):
    doc = Document()
    s = doc.sections[0]
    s.page_width=Cm(21); s.page_height=Cm(29.7)
    s.top_margin=Cm(1.8); s.bottom_margin=Cm(1.8)
    s.left_margin=Cm(2.2); s.right_margin=Cm(2.2)

    def ea(run, name="微軟正黑體"):
        rPr=run._r.get_or_add_rPr()
        f=rPr.find(qn('w:rFonts'))
        if f is None: f=OxmlElement('w:rFonts'); rPr.insert(0,f)
        for a in ('w:eastAsia','w:ascii','w:hAnsi'): f.set(qn(a),name)

    def R(run, sz=10, bold=False, color=None):
        run.font.size=Pt(sz); run.font.bold=bold
        if color: run.font.color.rgb=color
        ea(run)

    def P(p, sb=0, sa=4, align=WD_ALIGN_PARAGRAPH.LEFT):
        p.alignment=align
        p.paragraph_format.space_before=Pt(sb)
        p.paragraph_format.space_after=Pt(sa)

    def shd(cell, hex):
        tc=cell._tc; pr=tc.get_or_add_tcPr()
        s=OxmlElement('w:shd')
        s.set(qn('w:val'),'clear'); s.set(qn('w:color'),'auto')
        s.set(qn('w:fill'),hex); pr.append(s)

    def rh(row, cm):
        tr=row._tr; pr=tr.get_or_add_trPr()
        h=OxmlElement('w:trHeight')
        h.set(qn('w:val'),str(int(cm*567))); h.set(qn('w:hRule'),'atLeast')
        pr.append(h)

    def divider(doc, color='1F3864', sz='6'):
        p=doc.add_paragraph(); P(p,0,0)
        pPr=p._p.get_or_add_pPr(); b=OxmlElement('w:pBdr')
        e=OxmlElement('w:bottom')
        e.set(qn('w:val'),'single'); e.set(qn('w:sz'),sz)
        e.set(qn('w:space'),'1'); e.set(qn('w:color'),color)
        b.append(e); pPr.append(b)

    def sec(doc, text, fill='1F3864'):
        p=doc.add_paragraph(); P(p,sb=10,sa=5)
        pPr=p._p.get_or_add_pPr()
        s=OxmlElement('w:shd')
        s.set(qn('w:val'),'clear'); s.set(qn('w:color'),'auto')
        s.set(qn('w:fill'),fill); pPr.append(s)
        r=p.add_run(f'  {text}')
        R(r,sz=12,bold=True,color=RGBColor(0xFF,0xFF,0xFF))

    def lbl(cell, text, bg='EBF3FA', tc=None):
        shd(cell, bg)
        p=cell.paragraphs[0]
        P(p,sb=3,sa=3,align=WD_ALIGN_PARAGRAPH.CENTER)
        R(p.add_run(text),sz=9,bold=True,color=tc or RGBColor(0x1F,0x38,0x64))

    CW=[Cm(2.0),Cm(14.5)]
    def set_cw(tbl):
        for row in tbl.rows:
            for i,c in enumerate(row.cells): c.width=CW[i]

    def today_card(doc, idx, d):
        tbl=doc.add_table(rows=4,cols=2)
        tbl.style='Table Grid'; set_cw(tbl)

        r=tbl.rows[0]; rh(r,0.68)
        r.cells[0].merge(r.cells[1]); shd(r.cells[0],'1F3864')
        p=r.cells[0].paragraphs[0]; P(p,sb=2,sa=2)
        label=f'  第 {idx} 件事' + ('（最重要）' if idx==1 else '')
        R(p.add_run(label),sz=11,bold=True,color=RGBColor(0xFF,0xFF,0xFF))
        R(p.add_run('　　專案：'),sz=9,bold=True,color=RGBColor(0xCC,0xDD,0xFF))
        R(p.add_run(f"{d['project']}"),sz=10,bold=True,color=RGBColor(0xFF,0xFF,0x80))

        r=tbl.rows[1]; rh(r,1.7)
        lbl(r.cells[0],'今日\n結果')
        shd(r.cells[1],'FAFAFA')
        p=r.cells[1].paragraphs[0]; P(p,sb=4,sa=4)
        R(p.add_run(d['result']),sz=10)

        r=tbl.rows[2]; rh(r,0.72)
        lbl(r.cells[0],'配合\n／何時')
        shd(r.cells[1],'EBF3FA')
        p=r.cells[1].paragraphs[0]; P(p,sb=3,sa=3)
        R(p.add_run('需要誰配合：'),sz=9,bold=True,color=RGBColor(0x1F,0x38,0x64))
        R(p.add_run(f"{d['partner']}　　　　　　"),sz=9)
        R(p.add_run('何時前完成：'),sz=9,bold=True,color=RGBColor(0x1F,0x38,0x64))
        R(p.add_run(d['deadline']),sz=9)

        r=tbl.rows[3]; rh(r,1.0)
        lbl(r.cells[0],'進度')
        shd(r.cells[1],'F2F2F2')
        p=r.cells[1].paragraphs[0]; P(p,sb=3,sa=1)
        opts=['完成','進行中','延後']
        status_line='　'.join([f"{'■' if d['status']==o else '□'} {o}" for o in opts])
        R(p.add_run(status_line+'　　'),sz=9,bold=True,color=RGBColor(0x1F,0x38,0x64))
        if d.get('note'):
            R(p.add_run('｜ 需主管知道：'),sz=9,bold=True,color=RGBColor(0xC0,0x00,0x00))
            R(p.add_run(d['note']),sz=9,color=RGBColor(0xC0,0x00,0x00))
        else:
            R(p.add_run('｜ 需主管知道：（沒事留空）'),sz=9,color=RGBColor(0xB0,0xB0,0xB0))
        p2=r.cells[1].add_paragraph(); P(p2,sb=1,sa=3)
        R(p2.add_run('說明：'),sz=8,bold=True,color=RGBColor(0x60,0x60,0x60))
        if d.get('status_desc'):
            R(p2.add_run(d['status_desc']),sz=8)
        else:
            R(p2.add_run('完成→免填　進行中→目前到哪　延後→延到何時'),sz=8,color=RGBColor(0xB0,0xB0,0xB0))
        doc.add_paragraph().paragraph_format.space_after=Pt(6)

    def tmrw_card(doc, idx, d):
        tbl=doc.add_table(rows=3,cols=2)
        tbl.style='Table Grid'; set_cw(tbl)

        r=tbl.rows[0]; rh(r,0.68)
        r.cells[0].merge(r.cells[1]); shd(r.cells[0],'243F60')
        p=r.cells[0].paragraphs[0]; P(p,sb=2,sa=2)
        label=f'  第 {idx} 件事' + ('（最重要）' if idx==1 else '')
        R(p.add_run(label),sz=11,bold=True,color=RGBColor(0xFF,0xFF,0xFF))
        R(p.add_run('　　專案：'),sz=9,bold=True,color=RGBColor(0xAA,0xBB,0xDD))
        R(p.add_run(f"{d['project']}"),sz=10,bold=True,color=RGBColor(0xFF,0xFF,0xAA))

        r=tbl.rows[1]; rh(r,1.6)
        lbl(r.cells[0],'明日\n目標',bg='DAE3EE',tc=RGBColor(0x24,0x3F,0x60))
        shd(r.cells[1],'FAFAFA')
        p=r.cells[1].paragraphs[0]; P(p,sb=4,sa=4)
        R(p.add_run(d['goal']),sz=10)

        r=tbl.rows[2]; rh(r,0.72)
        lbl(r.cells[0],'配合\n／何時',bg='DAE3EE',tc=RGBColor(0x24,0x3F,0x60))
        shd(r.cells[1],'EBF3FA')
        p=r.cells[1].paragraphs[0]; P(p,sb=3,sa=3)
        R(p.add_run('需要誰配合：'),sz=9,bold=True,color=RGBColor(0x24,0x3F,0x60))
        R(p.add_run(f"{d['partner']}　　　　　　"),sz=9)
        R(p.add_run('何時前完成：'),sz=9,bold=True,color=RGBColor(0x24,0x3F,0x60))
        R(p.add_run(d['deadline']),sz=9)
        doc.add_paragraph().paragraph_format.space_after=Pt(6)

    # 文件本體
    p=doc.add_paragraph(); P(p,sb=0,sa=0,align=WD_ALIGN_PARAGRAPH.CENTER)
    R(p.add_run('寶舖建設集團｜開發部'),sz=9,color=RGBColor(0x80,0x80,0x80))
    p=doc.add_paragraph(); P(p,sb=2,sa=6,align=WD_ALIGN_PARAGRAPH.CENTER)
    R(p.add_run('每日工作日報'),sz=22,bold=True,color=RGBColor(0x1F,0x38,0x64))
    divider(doc)
    p=doc.add_paragraph(); P(p,sb=6,sa=6)
    R(p.add_run('日期：'),sz=11,bold=True); R(p.add_run(date_str),sz=11)
    R(p.add_run('          填報人：'),sz=11,bold=True); R(p.add_run(name),sz=11)
    divider(doc)

    sec(doc,'今日最重要三件事（按重要性排序）','1F3864')
    for i,d in enumerate(today_data,1): today_card(doc,i,d)

    sec(doc,'明日最重要三件事（按重要性排序）','243F60')
    for i,d in enumerate(tmrw_data,1): tmrw_card(doc,i,d)

    divider(doc,color='BFBFBF',sz='4')
    p=doc.add_paragraph(); P(p,sb=4,sa=0)
    R(p.add_run('每日下班後填寫，22:00 前繳交　｜　三件事請按重要性排序，第1件最重要　｜　「需主管知道」欄沒事留空，有事一行說清楚'),sz=8,color=RGBColor(0x80,0x80,0x80))

    # 存檔
    os.makedirs(out_dir, exist_ok=True)
    date_compact = date_str.replace(' ','').replace('年','').replace('月','').replace('日','')
    fname = f"{date_compact}-開發部-日報-{name}.docx"
    out_path = os.path.join(out_dir, fname)
    doc.save(out_path)
    return out_path
```
