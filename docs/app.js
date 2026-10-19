"use strict";
/* 업종 심리 지도 — 화면 로직
   보기: 심리 지도(map) / 3국 비교(cross) / 로테이션(rrg) / 연속성(streak) / 추세·폭(trend) / 신호 검증(signal)
   데이터: data/markets.json, data/<시장>/{index,history,signals,trend}.json, data/<시장>/weeks/<월요일>.json */

const DEF = {weight:"cw", mode:"fixed", turn:"tv", dR:1, wR:2, zR:1, dT:1.1, wT:1.05,
             unit:"sector", minn:5, freq:"week", tail:"8"};
const CAT = {hu:"거래 몰린 상승", qu:"조용한 상승", ch:"손바뀜", ca:"소강", ou:"관심 이탈", hd:"거래 몰린 하락"};
const SHORT = {hu:"몰↑", qu:"조↑", ch:"손", ca:"", ou:"이탈", hd:"몰↓"};
const CATS = ["hu","qu","ch","ca","ou","hd"];
const WD = ["월","화","수","목","금"];
const DSTATE = {"2":"완전 정배열","1":"정배열 진행","0":"혼조","-1":"역배열 진행","-2":"완전 역배열"};
const DCLS = {"2":"st2","1":"st1","0":"st0","-1":"stm1","-2":"stm2"};
const DESC = {
  map: "거래와 등락을 함께 본 그날의 업종 심리. 상대 등락은 시장 대비 %p, 상대 거래는 업종의 직전 20거래일 평균 대비 배수를 시장 배수로 나눈 값. 섹터 이름 앞 ▸ 를 누르면 산업이 펼쳐지고, 칸을 누르면 종목이 열림.",
  cross: "같은 업종을 미국·한국·일본에서 같은 주에 나란히 놓은 것. 세 시장이 같은 방향으로 기준을 넘으면 '공통', 반대로 넘으면 '엇갈림'. 각 칸은 해당 시장 안에서의 시장 대비 판정임.",
  rrg: "가로 = RS 추세(시장 대비 강도 ÷ 최근 10주 평균, 100 위면 평균보다 강함), 세로 = RS 모멘텀(RS 추세의 4주 변화, 100 위면 개선 중). 보통 개선 → 선도 → 약화 → 소외 순으로 시계 방향으로 돈다.",
  streak: "업종별 최근 12주 주간 판정 띠. 같은 판정이 이어지는 주 수(연속)를 보면 일회성 반짝인지 지속되는 흐름인지 구분할 수 있음.",
  trend: "종목별 이평 배열(일봉 5·20·60·120·200, 주봉 10·20·30·40), Weinstein Stage(30주선), Minervini 트렌드 템플릿 8조건과 업종 breadth(이평선 위 비율, 52주 신고가·신저가). 최신 거래일 기준 스냅샷.",
  macro: "환율·미국채 금리·신용 스프레드·채권 ETF·원자재·크립토·변동성·글로벌 지수. 금리·스프레드 변화는 bp, VIX 류는 포인트, 나머지는 %. 52주 위치는 최근 1년 범위에서 지금 값이 어디쯤인지(0=저점, 100=고점).",
  weekly: "한 주를 숫자로 요약. 위쪽은 세 나라 비교(실제 지수, 이 사이트 유니버스로 재구성한 시총가중·동일가중, 가운데 종목, 오른 종목 비율), 아래는 위에서 고른 시장의 상세(시총 증감 종목, 규모별, 강·약 산업, 업종 ETF). 문장은 숫자에서 규칙으로 만든 것이며 해석이 아님.",
  newhigh: "그날 상승·양봉 마감하며 장중 52주·역대 신고가를 낸 종목. 같은 섹터 라벨에 몰리면 군집으로 묶고, 종목마다 1년 차트·최근 공시·뉴스 헤드라인을 붙임. 재료는 '그날 나온 소식 목록'이지 원인 확정이 아님.",
  signal: "과거 판정이 다음 기간 시장 대비 성과와 연결되는지 집계한 것. 위의 가중·등락 기준·거래 기준·단위 선택을 그대로 따름. 표본·중첩·비용 한계는 아래 주의 사항 참고.",
};

let S = load(), MKT = "us", VIEW = "map", WEEK = null, SECF = "";
let MARKETS = [{key:"us", label:"미국", flag:"🇺🇸"}], INDEX = null, W = null;
let cache = {}, sortCol = "week", drill = null, expanded = new Set(), rrgSel = null;
let crossSort = "avg", trendF = {f:"all", sector:null, d:null, w:null};
let WKSEL = null, wkTab = "kr";
let NHDAY = null, nhF = {kind:"all", label:"", cluster:false}, followSort = -1;

/* ── 유틸 ─────────────────────────────── */
function load(){ try{ return {...DEF, ...JSON.parse(localStorage.getItem("sm-settings")||"{}")}; }catch(e){ return {...DEF}; } }
function save(){ try{ localStorage.setItem("sm-settings", JSON.stringify(S)); }catch(e){} }
const $ = s => document.querySelector(s);
const fmt = (x, d=1) => x==null || !isFinite(x) ? "–" : (x>0?"+":"") + x.toFixed(d);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const md = s => s.slice(5).replace("-","/");
async function getJSON(p){
  if(cache[p]) return cache[p];
  const r = await fetch(p, {cache:"no-cache"});
  if(!r.ok) throw new Error(p+" "+r.status);
  return cache[p] = await r.json();
}
async function tryJSON(p){ try{ return await getJSON(p); }catch(e){ return null; } }
function weekDates(key){
  const [y,m,d] = key.split("-").map(Number);
  return [0,1,2,3,4].map(i => new Date(Date.UTC(y,m-1,d+i)).toISOString().slice(0,10));
}
function heat(v, scale=5){
  if(v==null || !isFinite(v)) return "";
  const a = Math.min(Math.abs(v)/scale, 1)*0.55;
  return `background:${v>=0?`rgba(209,52,74,${a})`:`rgba(47,98,196,${a})`}`;
}
function moneyFmt(eok, cur){
  if(eok==null || !isFinite(eok)) return "–";
  const a = Math.abs(eok);
  return a >= 10000 ? (eok/10000).toFixed(a>=100000?1:2)+"조 "+cur : Math.round(eok).toLocaleString()+"억 "+cur;
}
const money = eok => moneyFmt(eok, INDEX?.currency || "달러");
function moneyDelta(eok){
  if(eok==null) return "–";
  const a = Math.abs(eok), sgn = eok>0 ? "+" : eok<0 ? "−" : "";
  return sgn + (a >= 10000 ? (a/10000).toFixed(2)+"조" : Math.round(a).toLocaleString()+"억");
}
function secName(key){ return W?.sectors.find(s => s.key===key)?.name || key; }

/* ── 분류 (파이썬 classify 와 같은 규칙) ── */
function classify(o, isWeek){
  if(!o) return {cls:null};
  const rel = S.weight==="cw" ? o.rc : o.re;
  const sig = S.weight==="cw" ? o.sc : o.se;
  const turn = o[S.turn];
  const z = (rel!=null && sig) ? rel/sig : null;
  if(rel==null || turn==null) return {cls:null, rel, z, turn};
  const x = S.mode==="sigma" ? z : rel;
  const thr = S.mode==="sigma" ? S.zR : (isWeek ? S.wR : S.dR);
  const hi = turn >= (isWeek ? S.wT : S.dT);
  let cls;
  if(x==null) cls = hi ? "ch" : "ca";
  else if(x >= thr) cls = hi ? "hu" : "qu";
  else if(x <= -thr) cls = hi ? "hd" : "ou";
  else cls = hi ? "ch" : "ca";
  return {cls, rel, z, turn};
}
const relKey = c => S.mode==="sigma" ? c.z : c.rel;

/* 이력(history.json) 그룹 선택 */
function hGroups(H){
  if(!H) return [];
  if(S.unit==="sector") return H.groups.sector;
  return H.groups.industry.filter(g => (!SECF || g.sector===SECF) && g.n >= S.minn);
}
function hIndex(H, key){
  if(!H) return -1;
  let i = H.weeks.indexOf(key);
  if(i >= 0) return i;
  for(i = H.weeks.length-1; i >= 0; i--) if(H.weeks[i] <= key) return i;
  return -1;
}
const hObj = (g, i) => i < 0 ? null : {rc:g.rc[i], re:g.re[i], sc:g.sc[i], se:g.se[i], tv:g.tv[i], vr:g.vr[i]};

/* ── 라우팅 ────────────────────────────── */
function setHash(){ history.replaceState(null, "", `#${MKT}/${VIEW}/${(VIEW==="newhigh" ? NHDAY : VIEW==="weekly" ? WKSEL : WEEK)||""}`); }
function parseHash(){
  const p = location.hash.slice(1).split("/").filter(Boolean);
  const out = {};
  for(const x of p){
    if(/^\d{4}-\d{2}-\d{2}$/.test(x)) out.week = x;
    else if(DESC[x]) out.view = x;
    else out.mkt = x;
  }
  return out;
}

async function init(){
  MARKETS = (await tryJSON("data/markets.json")) || MARKETS;
  const h = parseHash();
  if(h.view) VIEW = h.view;
  if(VIEW==="newhigh" && h.week) NHDAY = h.week;
  if(VIEW==="weekly" && h.week) WKSEL = h.week;
  $("#mtabs").innerHTML = MARKETS.length > 1 ? MARKETS.map(m => `<button data-m="${m.key}">${m.flag} ${m.label}</button>`).join("") : "";
  const keys = MARKETS.map(m => m.key);
  await openMarket(keys.includes(h.mkt) ? h.mkt : keys[0], h.week);
}

async function openMarket(key, week){
  MKT = key;
  document.querySelectorAll("#mtabs button").forEach(b => b.classList.toggle("on", b.dataset.m===key));
  INDEX = await tryJSON(`data/${MKT}/index.json`);
  if(!INDEX && VIEW==="macro"){ $("#meta").textContent = ""; syncControls(); await renderMacro(); return; }
  if(!INDEX && VIEW==="weekly"){ $("#meta").textContent = ""; syncControls(); await renderWeekly(); return; }
  if(!INDEX && VIEW==="newhigh"){ $("#meta").textContent = ""; syncControls(); setHash(); await renderNewhigh(); return; }
  if(!INDEX){
    $("#meta").textContent = "";
    $("#view").innerHTML = `<div class="card"><div class="empty-state">아직 데이터가 없음. GitHub Actions의 첫 실행(백필)이 끝나면 표시됨.</div></div>`;
    return;
  }
  $("#mtag").textContent = INDEX.label || "미국";
  document.title = `업종 심리 지도 · ${INDEX.label || "미국"}`;
  $("#meta").textContent = `최근 거래일 ${INDEX.last_day} · 유니버스 ${INDEX.universe} (시총 ${moneyFmt(INDEX.min_mcap/1e8, INDEX.currency||"달러")} 이상 → ${INDEX.n_stocks.toLocaleString()}종목, 월 1회 고정) · 갱신 ${INDEX.generated}`;
  $("#week").innerHTML = INDEX.weeks.slice().reverse().map(w => `<option value="${w}">${md(w)}(월) 주</option>`).join("");
  await openWeek(INDEX.weeks.includes(week) ? week : INDEX.weeks[INDEX.weeks.length-1]);
}

async function openWeek(key){
  WEEK = key;
  W = await getJSON(`data/${MKT}/weeks/${key}.json`);
  $("#week").value = key;
  const i = INDEX.weeks.indexOf(key);
  $("#prev").disabled = i<=0; $("#next").disabled = i>=INDEX.weeks.length-1;
  const secOpts = `<option value="">전체</option>` + W.sectors.map(s => `<option value="${esc(s.key)}">${esc(s.name)}</option>`).join("");
  if($("#secf").innerHTML !== secOpts) $("#secf").innerHTML = secOpts;
  if(SECF && !W.sectors.some(s => s.key===SECF)) SECF = "";
  $("#secf").value = SECF;
  render();
}

function syncControls(){
  document.querySelectorAll(".seg").forEach(g => g.querySelectorAll("button").forEach(b => b.classList.toggle("on", String(S[g.dataset.k])===b.dataset.v)));
  document.querySelectorAll("[data-t]").forEach(inp => inp.value = S[inp.dataset.t]);
  $("#minn").value = S.minn;
  document.querySelectorAll("#vtabs button").forEach(b => b.classList.toggle("on", b.dataset.v===VIEW));
  document.querySelectorAll("#bar [data-show]").forEach(el => {
    const ok = el.dataset.show.split(" ").includes(VIEW) && (!el.dataset.unit || el.dataset.unit===S.unit);
    el.classList.toggle("hide", !ok);
  });
  $("#vdesc").textContent = DESC[VIEW];
}

async function render(){
  if(VIEW==="newhigh"){ syncControls(); setHash(); await renderNewhigh(); return; }
  if(VIEW==="weekly"){ syncControls(); await renderWeekly(); return; }
  if(VIEW==="macro"){ syncControls(); setHash(); await renderMacro(); return; }
  if(!W) return;
  syncControls(); setHash();
  const fn = {map:renderMap, cross:renderCross, rrg:renderRRG, streak:renderStreak, trend:renderTrend, signal:renderSignal}[VIEW];
  await fn();
  if(drill) (drill.mode==="trend" ? renderTrendDrill : renderDrill)();
}

/* ══ 1. 심리 지도 ═════════════════════════ */
function cellHTML(c, attrs, isWeek){
  if(!c || c.cls==null) return `<td class="c empty${isWeek?" wk":""}">·</td>`;
  const val = S.mode==="sigma" && c.z!=null ? `${fmt(c.rel)}%p · ${fmt(c.z)}σ` : `${fmt(c.rel)}%p`;
  return `<td class="c ${c.cls}${isWeek?" wk":""}" ${attrs}><span class="k">${CAT[c.cls]}</span><span class="v mono">${val}</span></td>`;
}
function tip(name, c, o, isWeek, nd){
  if(!o) return name;
  const w = S.weight==="cw" ? "시총가중" : "동일가중";
  return `${name}\n상대 등락 ${fmt(c.rel,2)}%p (${w})` + (c.z!=null?` · ${fmt(c.z,2)}σ`:"") +
    `\n상대 거래대금 ${o.tv?.toFixed(2)}배 · 상대 거래량 ${o.vr?.toFixed(2)}배` +
    `\n시장 거래대금 중 ${o.sh?.toFixed(1)}% · 상승 종목 ${o.br}%` +
    (isWeek ? `\n시장 이긴 날 ${S.weight==="cw"?o.wc:o.we}/${nd}` : "");
}

function mapRows(){
  const dates = weekDates(W.week), have = new Set(W.days);
  const mk = (g, kind) => ({g, kind, wk: classify(g.week, true), d: dates.map(dt => have.has(dt) ? classify(g.day[dt], false) : null)});
  const key = r => sortCol==="week" ? relKey(r.wk) : (r.d[sortCol] ? relKey(r.d[sortCol]) : null);
  const sorter = (a,b) => (key(b) ?? -1e9) - (key(a) ?? -1e9);
  const inds = W.industries || [];
  if(S.unit==="industry"){
    return inds.filter(g => (!SECF || g.sector===SECF) && g.n >= S.minn).map(g => mk(g,"industry")).sort(sorter);
  }
  const rows = [];
  W.sectors.map(g => mk(g,"sector")).sort(sorter).forEach(r => {
    rows.push(r);
    if(expanded.has(r.g.key)) inds.filter(g => g.sector===r.g.key && g.n >= Math.min(S.minn, 3)).map(g => ({...mk(g,"industry"), sub:true})).sort(sorter).forEach(x => rows.push(x));
  });
  return rows;
}

async function renderMap(){
  const dates = weekDates(W.week);
  const rows = mapRows();
  const ev = W.events || {};
  const nInd = (W.industries||[]).length;
  let h = `<thead><tr><th class="l">${S.unit==="sector"?"섹터":"산업"}</th>` + dates.map((dt,i) =>
    `<th class="sortable${sortCol===i?" sorted":""}" data-sort="${i}">${WD[i]} <span class="mono">${md(dt)}</span>${ev[dt]?`<span class="ev" title="${esc(ev[dt].join(" · "))}">⚑</span>`:""}</th>`).join("") +
    `<th class="sortable wk${sortCol==="week"?" sorted":""}" data-sort="week">주간</th></tr></thead><tbody>`;
  const mk = W.market, mw = S.weight;
  h += `<tr class="mk"><td class="sec l">시장 <span>${mw==="cw"?"시총가중":"동일가중"}</span></td>` +
    dates.map(dt => mk.day[dt] ? `<td class="c mono" style="cursor:default">${fmt(mk.day[dt][mw])}% · ${mk.day[dt].tv?.toFixed(2)}배</td>` : `<td class="c empty">·</td>`).join("") +
    `<td class="c wk mono" style="cursor:default">${fmt(mk.week[mw])}% · ${mk.week.tv?.toFixed(2)}배</td></tr>`;
  const counts = {};
  for(const r of rows){
    if(!r.sub) counts[r.wk.cls] = (counts[r.wk.cls]||0)+1;
    const subN = r.kind==="sector" ? (W.industries||[]).filter(g => g.sector===r.g.key).length : 0;
    const tg = r.kind==="sector" && subN ? `<span class="tog" data-tog="${esc(r.g.key)}">${expanded.has(r.g.key)?"▾":"▸"}</span>` : (r.kind==="sector" ? `<span class="tog"></span>` : "");
    const sub = S.unit==="industry" ? `<small>${esc(secName(r.g.sector))}</small>` : "";
    h += `<tr class="${r.sub?"sub":""}"><td class="sec l">${tg}<b>${esc(r.g.name)}</b><span>${r.g.n}</span>${sub}</td>`;
    r.d.forEach((c,i) => {
      if(!c){ h += `<td class="c empty">·</td>`; return; }
      h += cellHTML(c, `data-kind="${r.kind}" data-key="${esc(r.g.key)}" data-day="${i}" title="${esc(tip(r.g.name+" · "+WD[i], c, r.g.day[dates[i]], false))}"`);
    });
    h += cellHTML(r.wk, `data-kind="${r.kind}" data-key="${esc(r.g.key)}" data-day="week" title="${esc(tip(r.g.name+" · 주간", r.wk, r.g.week, true, W.days.length))}"`, true);
    h += `</tr>`;
  }
  const legend = CATS.map(k => `<span class="lg"><i class="${k}"></i>${CAT[k]} <b>${counts[k]||0}</b></span>`).join("") +
    `<span class="lg" style="border:0;background:none">주간 기준 ${S.unit==="sector"?"섹터":"산업"} 수</span>`;
  const evTxt = Object.entries(ev).map(([d,e]) => `${md(d)} ${e.join("·")}`).join(" / ");
  const hint = S.unit==="sector" ? `섹터 앞 ▸ 로 산업 펼치기 (산업 ${nInd}개). ` : `산업 ${rows.length}개 표시 (최소 ${S.minn}종목). `;
  $("#view").innerHTML = `<div class="legend">${legend}</div>
    <div class="card"><div class="scroll"><table class="grid" id="grid">${h}</tbody></table></div></div>
    <div class="foot">${evTxt ? "⚑ "+esc(evTxt)+"  ·  " : ""}${hint}칸에 마우스를 올리면 세부 수치, 요일 머리글을 누르면 그날 기준 정렬.</div>
    <h2 class="sh">규모와 쏠림 <span class="tag">${mw==="cw"?"시총가중":"동일가중"}</span></h2>
    <p class="sdesc" id="szdesc"></p>
    <div class="card"><div class="scroll"><table class="tbl" id="sizeT"></table></div></div>
    ${ruleNote()}`;
  renderSize(dates);
}

function ruleNote(){
  return `<div class="note"><h3>분류 규칙</h3><table>
      <tr><th></th><th>거래 기준 이상</th><th>거래 기준 미만</th></tr>
      <tr><th>상승 기준 이상</th><td class="hu">거래 몰린 상승</td><td class="qu">조용한 상승</td></tr>
      <tr><th>그 사이</th><td class="ch">손바뀜</td><td class="ca">소강</td></tr>
      <tr><th>하락 기준 이하</th><td class="hd">거래 몰린 하락</td><td class="ou">관심 이탈</td></tr></table>
    고정 %p 모드: 일간 ±1%p·1.1배, 주간 ±2%p·1.05배. 변동성 σ 모드: 상대 등락을 업종 자신의 직전 60거래일 상대수익률 표준편차로 나눠 ±1σ로 판정(주간은 σ×√일수). 거래량 기준은 종목별 거래량 배수의 평균이라 주가 상승에 따른 거래대금 부풀림이 빠짐. 종목 수가 적은 산업은 몇 종목의 움직임이 판정을 좌우하므로 최소 종목 수를 함께 볼 것. ⚑ 는 옵션 만기·리밸런싱·시장 거래 급증일.</div>`;
}

function renderSize(dates){
  const z = W.size;
  if(!z || !z.buckets){ $("#sizeT").innerHTML = `<tr><td class="empty-state">이 주는 규모 데이터가 없음.</td></tr>`; return; }
  const w = S.weight;
  $("#szdesc").textContent = `규모는 연초 시가총액 순위 기준(${z.ref} 종가). 수익률은 절대값 %. 쏠림은 그날 거래대금 중 상위 ${z.conc?.top?.length||10}종목 몫.`;
  let h = `<thead><tr><th class="l">규모 (연초 시총 순위)</th><th class="wk">주간</th>` +
    dates.map((d,i) => `<th>${WD[i]} <span class="mono">${md(d)}</span></th>`).join("") + `</tr></thead><tbody>`;
  for(const b of z.buckets){
    const wv = b.week[w];
    h += `<tr><td class="l"><b>${esc(b.label)}</b><span>${b.n.toLocaleString()}</span></td><td class="wk mono ${wv>=0?"pos":"neg"}"><b>${wv==null?"–":fmt(wv,2)+"%"}</b></td>` +
      dates.map(d => { const v = b.day[d]?.[w]; return v==null ? `<td class="mono" style="color:var(--ink3)">·</td>` : `<td class="mono" style="${heat(v,3)}">${fmt(v,2)}</td>`; }).join("") + `</tr>`;
  }
  if(z.conc){
    const tops = (z.conc.top||[]).map(t => { const r = W.stocks.rows.find(x => x[0]===t); return r ? r[1] : t; });
    h += `<tr class="conc"><td class="l" title="${esc("주간 상위: "+tops.join(", "))}"><b>쏠림</b><span>거래대금 상위 ${tops.length||10} 몫</span></td><td class="wk mono">${z.conc.week==null?"–":z.conc.week.toFixed(1)+"%"}</td>` +
      dates.map(d => { const v = z.conc.day[d]; return `<td class="mono">${v==null?"·":v.toFixed(1)+"%"}</td>`; }).join("") + `</tr>`;
  }
  $("#sizeT").innerHTML = h + "</tbody>";
}

/* ── 지도 드릴다운 ── */
let dSort = {col:"mcap", dir:-1};
function openDrill(kind, key, day){
  drill = {mode:"map", kind, key, day};
  dSort = day==="week" ? {col:"mcap",dir:-1} : {col:"d"+day, dir:-1};
  $("#dtools").innerHTML = `<input type="search" id="q" placeholder="종목·산업 찾기"><span class="cnt" id="dcnt"></span>`;
  $("#q").addEventListener("input", () => renderDrill());
  openSheet(); renderDrill();
}
function openSheet(){ $("#sheet").classList.add("open"); document.body.style.overflow="hidden"; }
function closeDrill(){ drill=null; $("#sheet").classList.remove("open"); document.body.style.overflow=""; }

function renderDrill(){
  const isInd = drill.kind==="industry";
  const g = (isInd ? W.industries : W.sectors).find(x => x.key===drill.key);
  if(!g){ closeDrill(); return; }
  const dates = weekDates(W.week), have = W.days;
  const dayPos = dates.map(d => have.indexOf(d));
  const wk = g.week, cw = S.weight==="cw";
  const c = classify(wk, true);
  $("#crumb").textContent = `${INDEX.label||"미국"} · ${isInd ? "산업 · "+secName(g.sector) : "섹터"} · ${md(W.week)}(월) 주`;
  $("#dtitle").textContent = g.name;
  $("#dstats").innerHTML =
    `<span>주간 <b class="${(cw?g.ret_cw:g.ret_ew)>=0?"pos":"neg"} mono">${fmt(cw?g.ret_cw:g.ret_ew,2)}%</b></span>` +
    `<span>시장 대비 <b class="${c.rel>=0?"pos":"neg"} mono">${fmt(c.rel,2)}%p</b>${c.z!=null?` (${fmt(c.z,2)}σ)`:""}</span>` +
    `<span>이긴 날 <b>${cw?wk.wc:wk.we}/${have.length}</b></span>` +
    `<span>거래 몫 <b class="mono">${wk.sh?.toFixed(2)}%</b></span>` +
    `<span>상대 거래대금 <b class="mono">${wk.tv?.toFixed(2)}배</b></span>` +
    `<span>상대 거래량 <b class="mono">${wk.vr?.toFixed(2)}배</b></span>` +
    `<span>상승 종목 <b>${wk.br}%</b></span>` +
    `<span>판정 <b>${c.cls?CAT[c.cls]:"–"}</b></span>`;

  const q = ($("#q")?.value || "").trim().toLowerCase();
  const si = W.stocks.sectors.indexOf(isInd ? g.sector : g.key);
  const ii = isInd ? W.industries.findIndex(x => x.key===g.key) : -1;
  let rows = W.stocks.rows.filter(r => isInd ? r[11]===ii : r[2]===si);
  const total = rows.length;
  if(q) rows = rows.filter(r => (r[0]+" "+r[1]+" "+r[3]).toLowerCase().includes(q));
  const val = (r, col) => {
    if(col[0]==="d" && col!=="dmcap"){ const p = dayPos[+col.slice(1)]; return p<0 ? null : r[4][p]; }
    return {name:r[1], ind:r[3], week:r[5], up:r[6], share:r[7], valx:r[8], mcap:r[9], dmcap:r[10]}[col];
  };
  rows.sort((a,b) => {
    const x = val(a,dSort.col), y = val(b,dSort.col);
    if(x==null) return 1; if(y==null) return -1;
    return (typeof x==="string" ? x.localeCompare(y) : x-y) * dSort.dir;
  });
  $("#dcnt").textContent = q ? `${rows.length} / ${total}종목` : `${total}종목`;
  const hl = i => drill.day===i ? " hl" : "";
  const th = (col, label, cls="") => `<th class="sortable${dSort.col===col?" sorted":""}${cls}" data-col="${col}">${label}${dSort.col===col?(dSort.dir<0?" ▾":" ▴"):""}</th>`;
  let h = `<thead><tr><th>#</th>${th("name","종목"," l")}${th("ind","산업"," l")}` +
    dates.map((d,i) => th("d"+i, `${WD[i]} <span class="mono">${md(d)}</span>`, hl(i))).join("") +
    th("week","주간", drill.day==="week"?" hl":"") + th("up","상승일 거래") + th("share","거래 몫") + th("valx","거래 배수") + th("mcap","시총") + th("dmcap","시총 증감") + `</tr></thead><tbody>`;
  rows.forEach((r,n) => {
    h += `<tr><td class="mono" style="color:var(--ink3)">${n+1}</td><td class="nm l"><b>${esc(r[1])}</b><small class="mono">${esc(r[0])}</small></td><td class="ind l" title="${esc(r[3])}">${esc(r[3])}</td>`;
    dayPos.forEach((p,i) => { const v = p<0?null:r[4][p]; h += `<td class="mono${hl(i)}" style="${heat(v)}">${v==null?"·":fmt(v)}</td>`; });
    const up = r[6];
    h += `<td class="mono ${r[5]>=0?"pos":"neg"}${drill.day==="week"?" hl":""}" style="${heat(r[5],8)}">${r[5]==null?"–":fmt(r[5])+"%"}</td>` +
      `<td class="mono" style="${up==null?"":`background:rgba(${up>=50?"209,52,74":"47,98,196"},${Math.abs(up-50)/50*.5})`}">${up==null?"–":up+"%"}</td>` +
      `<td class="mono">${r[7]?.toFixed(2)}%</td><td class="mono">${r[8]==null?"–":r[8].toFixed(2)+"x"}</td><td class="mono">${money(r[9])}</td>` +
      `<td class="mono ${r[10]>0?"pos":r[10]<0?"neg":""}">${moneyDelta(r[10])}</td></tr>`;
  });
  $("#stocks").innerHTML = h + "</tbody>";
}

/* ══ 2. 3국 비교 ══════════════════════════ */
async function renderCross(){
  $("#view").innerHTML = `<div class="card"><div class="empty-state">세 시장 이력을 불러오는 중…</div></div>`;
  const Ms = await Promise.all(MARKETS.map(async m => ({...m, H: await tryJSON(`data/${m.key}/history.json`)})));
  const avail = Ms.filter(m => m.H);
  if(avail.length < 2){ $("#view").innerHTML = `<div class="card"><div class="empty-state">비교하려면 두 개 이상 시장의 이력 데이터가 필요함.</div></div>`; return; }
  avail.forEach(m => { m.i = hIndex(m.H, WEEK); m.wk = m.i>=0 ? m.H.weeks[m.i] : null; });
  const unit = S.unit;
  const keys = new Map();
  for(const m of avail){
    for(const g of (unit==="sector" ? m.H.groups.sector : m.H.groups.industry)){
      if(unit==="industry" && (g.n < S.minn || (SECF && g.sector!==SECF))) continue;
      if(!keys.has(g.key)) keys.set(g.key, {key:g.key, name:g.name, sector:g.sector, by:{}});
      keys.get(g.key).by[m.key] = g;
    }
  }
  const thr = S.mode==="sigma" ? S.zR : S.wR;
  let rows = [...keys.values()].filter(r => unit==="sector" || Object.keys(r.by).length >= 2).map(r => {
    const cells = avail.map(m => { const g = r.by[m.key]; return g ? {m, g, c: classify(hObj(g, m.i), true)} : {m}; });
    const xs = cells.filter(x => x.c && x.c.cls).map(x => relKey(x.c));
    const avg = xs.length ? xs.reduce((a,b)=>a+b,0)/xs.length : null;
    const ups = xs.filter(x => x >= thr).length, dns = xs.filter(x => x <= -thr).length;
    let tagHTML = "";
    if(xs.length >= 2 && ups === xs.length) tagHTML = `<span class="badge up">${xs.length}국 공통 강세</span>`;
    else if(xs.length >= 2 && dns === xs.length) tagHTML = `<span class="badge dn">${xs.length}국 공통 약세</span>`;
    else if(ups && dns) tagHTML = `<span class="badge">엇갈림</span>`;
    const sameSign = xs.length>=2 && (xs.every(x => x>0) || xs.every(x => x<0));
    return {...r, cells, avg, tagHTML, sameSign, tagRank: ups===xs.length||dns===xs.length ? 2 : (ups&&dns ? 1 : 0)};
  });
  const sk = crossSort;
  rows.sort((a,b) => {
    if(sk==="avg") return (b.avg??-1e9)-(a.avg??-1e9);
    if(sk==="tag") return b.tagRank-a.tagRank || (b.avg??-1e9)-(a.avg??-1e9);
    const v = r => { const c = r.cells.find(x => x.m.key===sk)?.c; return c && c.cls ? relKey(c) : -1e9; };
    return v(b)-v(a);
  });
  const nm = r => { if(unit==="sector") return secNameAny(r.key, r.name); const any = Object.values(r.by)[0]; return any.name; };
  let h = `<thead><tr><th class="l">${unit==="sector"?"섹터":"산업"}</th>` +
    avail.map(m => `<th class="sortable${sk===m.key?" sorted":""}" data-xs="${m.key}">${m.flag} ${m.label}<br><span class="mono" style="font-weight:400">${m.wk?md(m.wk)+" 주":"–"}</span></th>`).join("") +
    `<th class="sortable${sk==="avg"?" sorted":""}" data-xs="avg">평균</th><th class="sortable c${sk==="tag"?" sorted":""}" data-xs="tag">동조</th></tr></thead><tbody>`;
  for(const r of rows){
    h += `<tr><td class="sec l"><b>${esc(nm(r))}</b>${unit==="industry"?`<small>${esc(secNameAny(r.sector))}</small>`:""}</td>`;
    for(const x of r.cells){
      if(!x.g || !x.c || !x.c.cls){ h += `<td class="c empty xc">·</td>`; continue; }
      const stale = x.m.wk !== WEEK ? `<span class="stale">${md(x.m.wk)} 주 기준</span>` : "";
      const val = S.mode==="sigma" && x.c.z!=null ? `${fmt(x.c.rel)}%p · ${fmt(x.c.z)}σ` : `${fmt(x.c.rel)}%p`;
      h += `<td class="c xc ${x.c.cls}" data-xm="${x.m.key}" data-key="${esc(r.key)}" data-kind="${unit}" title="${esc(`${x.m.label} · ${x.g.name} (${x.g.n}종목)\n상대 거래 ${x.c.turn?.toFixed(2)}배`)}"><span class="k">${CAT[x.c.cls]}</span><span class="v mono">${val}</span>${stale}</td>`;
    }
    h += `<td class="mono ${r.avg>=0?"pos":"neg"}">${r.avg==null?"–":fmt(r.avg,2)+(S.mode==="sigma"?"σ":"%p")}</td><td class="ctr">${r.tagHTML}</td></tr>`;
  }
  const nCommonUp = rows.filter(r => r.tagHTML.includes("강세")).length, nCommonDn = rows.filter(r => r.tagHTML.includes("약세")).length;
  $("#view").innerHTML = `<div class="legend"><span class="lg">공통 강세 <b>${nCommonUp}</b></span><span class="lg">공통 약세 <b>${nCommonDn}</b></span><span class="lg">엇갈림 <b>${rows.filter(r=>r.tagHTML.includes("엇갈림")).length}</b></span>
      <span class="lg" style="border:0;background:none">주간 기준 · ${S.mode==="sigma"?`±${S.zR}σ`:`±${S.wR}%p`}</span></div>
    <div class="card"><div class="scroll"><table class="grid" id="crossT">${h}</tbody></table></div></div>
    <div class="foot">칸을 누르면 그 시장의 같은 주 종목 목록이 열림. 시장마다 휴장일·장 마감 시각이 달라 최신 주가 다를 수 있음(주황 표시). 각 시장 수익률은 지수가 아니라 유니버스 평균 대비임.</div>
    ${ruleNote()}`;
}
function secNameAny(key, fallback){
  const n = W?.sectors.find(s => s.key===key)?.name;
  return n || fallback || key;
}

/* ══ 4. 로테이션 ═══════════════════════════ */
const QD = {lead:{n:"선도", c:"var(--s2)", bg:"var(--q-lead)"}, weak:{n:"약화", c:"var(--s3)", bg:"var(--q-weak)"},
            lag:{n:"소외", c:"var(--s4)", bg:"var(--q-lag)"}, imp:{n:"개선", c:"var(--dn)", bg:"var(--q-imp)"}};
const quad = (x,y) => x>=100 ? (y>=100?"lead":"weak") : (y>=100?"imp":"lag");

async function renderRRG(){
  const H = await tryJSON(`data/${MKT}/history.json`);
  if(!H){ $("#view").innerHTML = `<div class="card"><div class="empty-state">이력 데이터가 아직 없음.</div></div>`; return; }
  const i = hIndex(H, WEEK), T = +S.tail, w = S.weight;
  const groups = hGroups(H).map(g => {
    const pts = [];
    for(let k = Math.max(0, i-T); k <= i; k++){ const x = g["x_"+w][k], y = g["y_"+w][k]; if(x!=null && y!=null) pts.push({x, y, wk:H.weeks[k]}); }
    return {g, pts};
  }).filter(o => o.pts.length);
  if(!groups.length){ $("#view").innerHTML = `<div class="card"><div class="empty-state">이 주는 로테이션 좌표를 계산할 이력이 부족함(최소 14주 필요).</div></div>`; return; }
  let dx = 1, dy = 1;
  for(const o of groups) for(const p of o.pts){ dx = Math.max(dx, Math.abs(p.x-100)); dy = Math.max(dy, Math.abs(p.y-100)); }
  dx *= 1.12; dy *= 1.12;
  const Wd = 760, Ht = 560, m = {l:46, r:16, t:16, b:36};
  const sx = x => m.l + (x-(100-dx))/(2*dx)*(Wd-m.l-m.r);
  const sy = y => m.t + (1-(y-(100-dy))/(2*dy))*(Ht-m.t-m.b);
  const cx = sx(100), cy = sy(100);
  let svg = `<svg viewBox="0 0 ${Wd} ${Ht}" role="img" aria-label="업종 로테이션 맵">
    <rect x="${cx}" y="${m.t}" width="${Wd-m.r-cx}" height="${cy-m.t}" fill="${QD.lead.bg}"/>
    <rect x="${cx}" y="${cy}" width="${Wd-m.r-cx}" height="${Ht-m.b-cy}" fill="${QD.weak.bg}"/>
    <rect x="${m.l}" y="${cy}" width="${cx-m.l}" height="${Ht-m.b-cy}" fill="${QD.lag.bg}"/>
    <rect x="${m.l}" y="${m.t}" width="${cx-m.l}" height="${cy-m.t}" fill="${QD.imp.bg}"/>
    <line x1="${cx}" y1="${m.t}" x2="${cx}" y2="${Ht-m.b}" stroke="var(--ink3)" stroke-width="1"/>
    <line x1="${m.l}" y1="${cy}" x2="${Wd-m.r}" y2="${cy}" stroke="var(--ink3)" stroke-width="1"/>
    <text x="${Wd-m.r-8}" y="${m.t+18}" text-anchor="end" font-size="13" font-weight="600" fill="${QD.lead.c}">선도</text>
    <text x="${Wd-m.r-8}" y="${Ht-m.b-8}" text-anchor="end" font-size="13" font-weight="600" fill="${QD.weak.c}">약화</text>
    <text x="${m.l+8}" y="${Ht-m.b-8}" font-size="13" font-weight="600" fill="${QD.lag.c}">소외</text>
    <text x="${m.l+8}" y="${m.t+18}" font-size="13" font-weight="600" fill="${QD.imp.c}">개선</text>
    <text x="${(m.l+Wd-m.r)/2}" y="${Ht-8}" text-anchor="middle" font-size="11" fill="var(--ink2)">RS 추세 →</text>
    <text x="14" y="${(m.t+Ht-m.b)/2}" text-anchor="middle" font-size="11" fill="var(--ink2)" transform="rotate(-90 14 ${(m.t+Ht-m.b)/2})">RS 모멘텀 →</text>
    <text x="${m.l}" y="${Ht-m.b+14}" font-size="10" fill="var(--ink3)" class="mono">${(100-dx).toFixed(1)}</text>
    <text x="${Wd-m.r}" y="${Ht-m.b+14}" text-anchor="end" font-size="10" fill="var(--ink3)">${(100+dx).toFixed(1)}</text>
    <text x="${m.l-4}" y="${m.t+10}" text-anchor="end" font-size="10" fill="var(--ink3)">${(100+dy).toFixed(1)}</text>
    <text x="${m.l-4}" y="${Ht-m.b}" text-anchor="end" font-size="10" fill="var(--ink3)">${(100-dy).toFixed(1)}</text>`;
  const many = groups.length > 25;
  for(const o of groups){
    const head = o.pts[o.pts.length-1], q = quad(head.x, head.y), col = QD[q].c;
    const dim = rrgSel && rrgSel!==o.g.key, on = rrgSel===o.g.key;
    const op = dim ? .12 : 1;
    const d = o.pts.map((p,k) => `${k?"L":"M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
    svg += `<g opacity="${op}" data-rg="${esc(o.g.key)}" style="cursor:pointer"><title>${esc(`${o.g.name} (${QD[q].n})\nRS 추세 ${head.x.toFixed(2)} · 모멘텀 ${head.y.toFixed(2)}`)}</title>`;
    svg += `<path d="${d}" fill="none" stroke="${col}" stroke-width="${on?2.5:1.5}" stroke-opacity=".7"/>`;
    o.pts.slice(0,-1).forEach(p => svg += `<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="2" fill="${col}" fill-opacity=".55"/>`);
    svg += `<circle cx="${sx(head.x).toFixed(1)}" cy="${sy(head.y).toFixed(1)}" r="${on?7:5}" fill="${col}" stroke="var(--panel)" stroke-width="1.5"/>`;
    if(!many || on) svg += `<text x="${(sx(head.x)+8).toFixed(1)}" y="${(sy(head.y)+4).toFixed(1)}" font-size="11.5" font-weight="${on?700:500}" fill="var(--ink)">${esc(o.g.name)}</text>`;
    svg += `</g>`;
  }
  svg += `</svg>`;
  const k4 = Math.max(0, i-4);
  const list = groups.map(o => {
    const head = o.pts[o.pts.length-1], q = quad(head.x, head.y);
    const px = o.g["x_"+w][k4], py = o.g["y_"+w][k4];
    const pq = px!=null && py!=null ? quad(px, py) : null;
    return {o, head, q, pq, dist: Math.hypot(head.x-100, head.y-100)};
  });
  const order = {lead:0, imp:1, weak:2, lag:3};
  list.sort((a,b) => order[a.q]-order[b.q] || b.dist-a.dist);
  let lh = `<thead><tr><th class="l">${S.unit==="sector"?"섹터":"산업"}</th><th>추세</th><th>모멘텀</th><th class="l">4주 전 → 지금</th></tr></thead><tbody>`;
  for(const x of list){
    const moved = x.pq && x.pq!==x.q ? `${QD[x.pq].n} → <b>${QD[x.q].n}</b>` : QD[x.q].n;
    lh += `<tr data-rg="${esc(x.o.g.key)}" class="${rrgSel===x.o.g.key?"on":""}"><td class="l"><span class="qd" style="background:${QD[x.q].c}"></span>${esc(x.o.g.name)}</td><td class="mono">${x.head.x.toFixed(1)}</td><td class="mono">${x.head.y.toFixed(1)}</td><td class="l">${moved}</td></tr>`;
  }
  const cnt = q => list.filter(x => x.q===q).length;
  $("#view").innerHTML = `<div class="legend">${Object.entries(QD).map(([k,v]) => `<span class="lg"><i style="background:${v.c}"></i>${v.n} <b>${cnt(k)}</b></span>`).join("")}
      <span class="lg" style="border:0;background:none">${md(H.weeks[i])} 주 · 꼬리 ${T}주 · ${w==="cw"?"시총가중":"동일가중"}</span></div>
    <div class="rrg-wrap"><div class="card rrg">${svg}</div>
    <div class="card" style="max-height:600px;overflow:auto"><table class="rlist">${lh}</tbody></table></div></div>
    <div class="foot">${many ? "업종이 많아 이름은 선택한 항목만 표시함. 오른쪽 목록이나 점을 누르면 강조됨. " : "점이나 목록을 누르면 강조, 다시 누르면 해제. "}좌표는 JdK RRG의 공개 근사식(RS÷10주 평균, 4주 변화)이라 상용 RRG 값과 정확히 같지는 않음.</div>`;
}

/* ══ 5. 연속성 ═════════════════════════════ */
async function renderStreak(){
  const H = await tryJSON(`data/${MKT}/history.json`);
  if(!H){ $("#view").innerHTML = `<div class="card"><div class="empty-state">이력 데이터가 아직 없음.</div></div>`; return; }
  const i = hIndex(H, WEEK), N = 12;
  const ks = []; for(let k = Math.max(0, i-N+1); k <= i; k++) ks.push(k);
  const rows = hGroups(H).map(g => {
    const cs = ks.map(k => classify(hObj(g,k), true).cls);
    const cur = cs[cs.length-1];
    let streak = 0; for(let k = cs.length-1; k >= 0 && cs[k]===cur; k--) streak++;
    // 같은 방향(상승계열/하락계열) 연속
    const dir = c => c==="hu"||c==="qu" ? 1 : c==="hd"||c==="ou" ? -1 : 0;
    let dstreak = 0; const dc = dir(cur); if(dc) for(let k = cs.length-1; k >= 0 && dir(cs[k])===dc; k--) dstreak++;
    const upN = cs.filter(c => dir(c)===1).length, dnN = cs.filter(c => dir(c)===-1).length;
    return {g, cs, cur, streak, dstreak, dc, upN, dnN};
  });
  rows.sort((a,b) => (b.cur!=="ca") - (a.cur!=="ca") || b.dstreak - a.dstreak || b.streak - a.streak || (b.upN-b.dnN)-(a.upN-a.dnN));
  let h = `<thead><tr><th class="l">${S.unit==="sector"?"섹터":"산업"}</th>` + ks.map(k => `<th class="c" style="padding:8px 2px;font-size:11px">${md(H.weeks[k])}</th>`).join("") +
    `<th class="l">이번 판정</th><th>같은 판정</th><th>같은 방향</th><th>12주 상승·하락</th></tr></thead><tbody>`;
  for(const r of rows){
    h += `<tr><td class="l"><b>${esc(r.g.name)}</b> <span style="color:var(--ink3);font-size:12px">${r.g.n}</span></td>` +
      r.cs.map((c,j) => `<td class="s ${c||""}" title="${esc(md(H.weeks[ks[j]])+" 주 · "+(c?CAT[c]:"자료 없음"))}">${c?SHORT[c]:"·"}</td>`).join("") +
      `<td class="l">${r.cur?`<span class="state ${r.cur}" style="min-width:auto;padding:2px 8px">${CAT[r.cur]}</span>`:"–"}</td>` +
      `<td class="mono">${r.cur && r.cur!=="ca" ? r.streak+"주" : "–"}</td>` +
      `<td class="mono ${r.dc>0?"pos":r.dc<0?"neg":""}">${r.dc ? (r.dc>0?"▲ ":"▼ ")+r.dstreak+"주" : "–"}</td>` +
      `<td class="mono"><span class="pos">${r.upN}</span> · <span class="neg">${r.dnN}</span></td></tr>`;
  }
  $("#view").innerHTML = `<div class="legend">${CATS.map(k => `<span class="lg"><i class="${k}"></i>${CAT[k]}${SHORT[k]?` (${SHORT[k]})`:""}</span>`).join("")}</div>
    <div class="card"><div class="scroll"><table class="tbl strip">${h}</tbody></table></div></div>
    <div class="foot">'같은 방향'은 거래 몰린/조용한 상승을 상승 계열로, 관심 이탈/거래 몰린 하락을 하락 계열로 묶어 센 연속 주 수. 정렬: 이번 주 소강이 아닌 업종 중 같은 방향 연속이 긴 순.</div>`;
}

/* ══ 6·7. 추세·폭 ══════════════════════════ */
function distBar(d, keys, colors, n){
  return `<div class="dist" title="${esc(keys.map(k => `${colors[k][1]} ${d[k]||0}`).join(" · "))}">` +
    keys.map(k => `<i style="width:${n?(d[k]||0)/n*100:0}%;background:${colors[k][0]}"></i>`).join("") + `</div>`;
}
const DCOL = {"2":["var(--c-hu)","완전 정배열"],"1":["var(--c-qu)","정배열 진행"],"0":["var(--c-ca)","혼조"],"-1":["var(--c-ou)","역배열 진행"],"-2":["var(--c-hd)","완전 역배열"]};
const SCOL = {"1":["var(--s1)","1 바닥"],"2":["var(--s2)","2 상승"],"3":["var(--s3)","3 천장"],"4":["var(--s4)","4 하락"]};
function spark(arr, w=110, h=26, lo=0, hi=100){
  const v = arr.map(x => x==null?null:x);
  const pts = v.map((x,i) => x==null?null:[i/(v.length-1||1)*w, h-(x-lo)/(hi-lo||1)*h]).filter(Boolean);
  if(pts.length < 2) return "";
  const mid = h-(50-lo)/(hi-lo)*h;
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><line x1="0" y1="${mid}" x2="${w}" y2="${mid}" stroke="var(--line)"/><path d="${pts.map((p,i)=>`${i?"L":"M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("")}" fill="none" stroke="var(--accent)" stroke-width="1.5"/></svg>`;
}
function lineChart(weeks, series, h=180){
  const Wd = 760, m = {l:34, r:12, t:12, b:24};
  const n = weeks.length; if(n < 2) return "";
  const sx = i => m.l + i/(n-1)*(Wd-m.l-m.r), sy = v => m.t + (1-v/100)*(h-m.t-m.b);
  let s = `<svg viewBox="0 0 ${Wd} ${h}" style="width:100%;height:auto">`;
  [0,25,50,75,100].forEach(v => s += `<line x1="${m.l}" x2="${Wd-m.r}" y1="${sy(v)}" y2="${sy(v)}" stroke="var(--line2)"/><text x="${m.l-6}" y="${sy(v)+3}" text-anchor="end" font-size="10" fill="var(--ink3)">${v}</text>`);
  [0, Math.floor((n-1)/2), n-1].forEach(i => s += `<text x="${sx(i)}" y="${h-6}" text-anchor="middle" font-size="10" fill="var(--ink3)">${md(weeks[i])}</text>`);
  for(const se of series){
    const d = se.v.map((v,i) => v==null?"":`${i&&se.v[i-1]!=null?"L":"M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join("");
    s += `<path d="${d}" fill="none" stroke="${se.c}" stroke-width="2"/>`;
  }
  return s + `</svg>`;
}

async function renderTrend(){
  const T = await tryJSON(`data/${MKT}/trend.json`);
  if(!T){ $("#view").innerHTML = `<div class="card"><div class="empty-state">추세 데이터가 아직 없음.</div></div>`; return; }
  const M = T.market, n = M.n;
  const pct = (a,b) => b ? (a/b*100).toFixed(1)+"%" : "–";
  const s2 = M.stage["2"], s2p = M.stage2_prev;
  const rows = T.stocks.rows;
  const newUp = rows.filter(r => r[12]===1).length, lost = rows.filter(r => r[12]===-1).length;
  const newS2 = rows.filter(r => r[7]===2 && r[8]!==2 && r[8]!=null).length;
  const kpi = (l, v, d) => `<div class="kpi"><div class="l">${l}</div><div class="n mono">${v}</div><div class="d">${d||""}</div></div>`;
  const kpis = kpi("50일선 위", (M.a50??"–")+"%", `1주 전 ${M.a50_prev??"–"}%`) + kpi("200일선 위", (M.a200??"–")+"%", "") +
    kpi("Stage 2 (상승)", pct(s2, n), `${s2.toLocaleString()}종목 · 지난주 ${s2p.toLocaleString()}`) +
    kpi("일봉 완전 정배열", pct(M.d["2"], n), `오늘 신규 ${newUp} · 이탈 ${lost}`) +
    kpi("Minervini 8/8", M.tt.toLocaleString()+"종목", pct(M.tt, n)) +
    kpi("52주 신고가 − 신저가", fmt(M.nh-M.nl,0), `오늘 ${M.nh}·${M.nl} / 이번 주 ${M.nh_w}·${M.nl_w}`);
  const hist = T.history;
  const chart = lineChart(hist.weeks, [{v:hist.market.a50, c:"var(--accent)"},{v:hist.market.a200, c:"var(--warn)"},{v:hist.market.s2, c:"var(--up)"}]);

  const dk = ["2","1","0","-1","-2"], sk = ["2","1","3","4"];
  let st = `<thead><tr><th class="l">섹터</th><th class="l">일봉 배열 분포</th><th>주봉 정배열</th><th class="l">Stage 분포</th><th>Stage 2</th><th>8/8</th><th>50일선 위</th><th>200일선 위</th><th>신고가·신저가 (주)</th><th class="l">50일선 위 추이</th></tr></thead><tbody>`;
  const secs = T.sectors.slice().sort((a,b) => (b.a50??0)-(a.a50??0));
  for(const s of secs){
    const wUp = (s.w["2"]||0)+(s.w["1"]||0);
    const d2 = s.stage["2"] - s.stage2_prev;
    const h50 = hist.sectors[s.key]?.a50 || [];
    st += `<tr class="click" data-tsec="${esc(s.key)}"><td class="l"><b>${esc(s.name)}</b><span>${s.n}</span></td>
      <td class="l">${distBar(s.d, dk, DCOL, s.n)}</td><td class="mono">${pct(wUp, s.n)}</td>
      <td class="l">${distBar(s.stage, sk, SCOL, s.n)}</td>
      <td class="mono">${pct(s.stage["2"], s.n)} <span class="${d2>0?"pos":d2<0?"neg":""}" style="font-size:11px">${d2?fmt(d2,0):""}</span></td>
      <td class="mono">${s.tt}</td>
      <td class="mono" style="${heat((s.a50??50)-50, 40)}">${s.a50??"–"}% <span style="font-size:11px;color:var(--ink3)">${s.a50!=null&&s.a50_prev!=null?fmt(s.a50-s.a50_prev,0):""}</span></td>
      <td class="mono" style="${heat((s.a200??50)-50, 40)}">${s.a200??"–"}%</td>
      <td class="mono"><span class="pos">${s.nh_w}</span> · <span class="neg">${s.nl_w}</span></td>
      <td class="l">${spark(h50)}</td></tr>`;
  }
  // 일봉 × 주봉 교차표 (시장 전체)
  const mx = {};
  rows.forEach(r => { if(r[6]==null) return; const k = r[4]+"|"+r[6]; mx[k] = (mx[k]||0)+1; });
  let mh = `<thead><tr><th>일봉 ↓ / 주봉 →</th>${dk.map(k => `<th>${DSTATE[k]}</th>`).join("")}</tr></thead><tbody>`;
  for(const d of dk){
    mh += `<tr><th style="text-align:left">${DSTATE[d]}</th>` + dk.map(w => { const v = mx[d+"|"+w]||0; return `<td class="mono${v?"":" z"}" data-mx="${d}|${w}" style="${v?heat((+d + +w)*1.0*(v/Math.max(...Object.values(mx)))*2.5, 5):""}">${v||"·"}</td>`; }).join("") + `</tr>`;
  }
  $("#view").innerHTML = `<div class="kpis">${kpis}</div>
    <div class="card" style="padding:12px 14px"><div style="font-size:12.5px;color:var(--ink2);margin-bottom:6px">시장 breadth 추이 (주간) — <span style="color:var(--accent)">■ 50일선 위</span> · <span style="color:var(--warn)">■ 200일선 위</span> · <span style="color:var(--up)">■ Stage 2 비율</span> (%)</div>${chart}</div>
    <h2 class="sh">섹터별 추세·폭 <span class="tag">${T.asof} 기준</span></h2>
    <p class="sdesc">행을 누르면 그 섹터 종목의 이평 배열·Stage·Minervini 상태가 열림. 막대: 일봉 배열(빨강=정배열 → 파랑=역배열), Stage(초록=2 상승, 주황=3 천장, 빨강=4 하락, 회색=1 바닥).</p>
    <div class="card"><div class="scroll"><table class="tbl">${st}</tbody></table></div></div>
    <h2 class="sh">일봉 × 주봉 배열 교차</h2>
    <p class="sdesc">시장 전체 종목 수. 예: 주봉 정배열인데 일봉이 혼조·역배열 진행이면 큰 추세 안의 눌림 구간 후보. 칸을 누르면 해당 종목 목록이 열림.</p>
    <div class="card"><div class="scroll"><table class="mx" style="width:auto;min-width:100%">${mh}</tbody></table></div></div>
    <div class="filters" style="margin-top:14px">
      <button class="chipb" data-tq="newup">신규 완전 정배열 ${newUp}</button>
      <button class="chipb" data-tq="lost">정배열 이탈 ${lost}</button>
      <button class="chipb" data-tq="news2">Stage 2 신규 진입 ${newS2}</button>
      <button class="chipb" data-tq="tt">Minervini 8/8 ${M.tt}</button>
    </div>
    <div class="note"><h3>정의</h3>
      완전 정배열: 가격 > ${T.daily_mas.join(" > ")}일선(주봉은 가격 > ${T.weekly_mas.join(" > ")}주선). 정배열 진행: 가운데 세 선만 정렬(일봉 20>60>120, 주봉 20>30>40). 역배열은 반대.
      Stage: 30주선 4주 기울기 +1% 초과면 가격이 위=2·아래=3, −1% 미만이면 가격이 아래=4·위=1, 그 사이(횡보)는 26주 전보다 30주선이 높으면 3, 아니면 1.
      Minervini 8조건: 가격>150·200일선, 150>200일선, 200일선 1개월 상승, 50일선>150·200일선, 가격>50일선, 52주 저점 대비 +30% 이상, 52주 고점 대비 −25% 이내, RS 등급 70 이상(3·6·9·12개월 수익률 40·20·20·20 가중, 이 시장 유니버스 내 백분위).</div>`;
}

function openTrendDrill(opts){
  trendF = {f:"all", sector:null, d:null, w:null, ...opts};
  drill = {mode:"trend"};
  dSort = {col:"mcap", dir:-1};
  const chips = [["all","전체"],["full","완전 정배열"],["newup","신규 정배열"],["lost","정배열 이탈"],["s2","Stage 2"],["news2","Stage 2 신규"],["tt","8/8"],["rs80","RS 80+"]];
  $("#dtools").innerHTML = `<input type="search" id="q" placeholder="종목·산업 찾기"><div class="filters" id="tchips">${chips.map(([k,l]) => `<button class="chipb" data-tf="${k}">${l}</button>`).join("")}</div><span class="cnt" id="dcnt"></span>`;
  $("#q").addEventListener("input", () => renderTrendDrill());
  $("#tchips").addEventListener("click", e => { const b = e.target.closest("[data-tf]"); if(!b) return; trendF.f = b.dataset.tf; renderTrendDrill(); });
  openSheet(); renderTrendDrill();
}

async function renderTrendDrill(){
  const T = await tryJSON(`data/${MKT}/trend.json`);
  if(!T) return;
  const sname = trendF.sector ? (T.sectors.find(s => s.key===trendF.sector)?.name || trendF.sector) : "시장 전체";
  $("#crumb").textContent = `${INDEX.label||"미국"} · 추세·폭 · ${T.asof} 기준`;
  $("#dtitle").textContent = sname + (trendF.d!=null ? ` · 일봉 ${DSTATE[trendF.d]} × 주봉 ${DSTATE[trendF.w]}` : "");
  const si = trendF.sector ? T.stocks.sectors.indexOf(trendF.sector) : -1;
  let rows = T.stocks.rows.filter(r => si<0 || r[2]===si);
  if(trendF.d!=null) rows = rows.filter(r => String(r[4])===trendF.d && String(r[6])===trendF.w);
  const base = rows.length;
  const F = {all:()=>true, full:r=>r[4]===2, newup:r=>r[12]===1, lost:r=>r[12]===-1, s2:r=>r[7]===2, news2:r=>r[7]===2&&r[8]!=null&&r[8]!==2, tt:r=>r[9]===8, rs80:r=>r[10]>=80};
  rows = rows.filter(F[trendF.f]);
  const q = ($("#q")?.value||"").trim().toLowerCase();
  const inds = T.stocks.industries;
  if(q) rows = rows.filter(r => (r[0]+" "+r[1]+" "+(inds[r[3]]||"")).toLowerCase().includes(q));
  document.querySelectorAll("#tchips [data-tf]").forEach(b => b.classList.toggle("on", b.dataset.tf===trendF.f));
  const s = T.sectors.find(x => x.key===trendF.sector) || T.market;
  $("#dstats").innerHTML = `<span>종목 <b>${s.n}</b></span><span>일봉 완전 정배열 <b>${s.d["2"]}</b></span><span>Stage 2 <b>${s.stage["2"]}</b></span><span>8/8 <b>${s.tt}</b></span><span>50일선 위 <b>${s.a50??"–"}%</b></span><span>200일선 위 <b>${s.a200??"–"}%</b></span><span>이번 주 신고가·신저가 <b>${s.nh_w}·${s.nl_w}</b></span>`;
  const val = (r,c) => ({name:r[1], ind:inds[r[3]]||"", d:r[4]*1000+r[5], w:r[6], stage:r[7], tt:r[9], rs:r[10], hi:r[11], mcap:r[13], g20:r[14][1], g200:r[14][4]}[c]);
  rows.sort((a,b) => { const x = val(a,dSort.col), y = val(b,dSort.col); if(x==null) return 1; if(y==null) return -1; return (typeof x==="string"?x.localeCompare(y):x-y)*dSort.dir; });
  $("#dcnt").textContent = `${rows.length} / ${base}종목`;
  const th = (col, label, cls="") => `<th class="sortable${dSort.col===col?" sorted":""}${cls}" data-col="${col}">${label}${dSort.col===col?(dSort.dir<0?" ▾":" ▴"):""}</th>`;
  let h = `<thead><tr><th>#</th>${th("name","종목"," l")}${th("ind","산업"," l")}${th("d","일봉 배열"," c")}${th("w","주봉 배열"," c")}${th("stage","Stage"," c")}${th("tt","Minervini")}${th("rs","RS")}${th("hi","52주 고점 대비")}` +
    T.daily_mas.map((m,i) => i===1 ? th("g20", `이격 ${m}`) : i===4 ? th("g200", `이격 ${m}`) : `<th>이격 ${m}</th>`).join("") + th("mcap","시총") + `</tr></thead><tbody>`;
  rows.slice(0, 600).forEach((r,n) => {
    const chg = r[12]===1 ? ` <span class="pos" title="오늘 신규 진입">●</span>` : r[12]===-1 ? ` <span class="neg" title="오늘 이탈">○</span>` : "";
    const sg = r[7]==null ? "–" : (r[8]!=null && r[8]!==r[7] ? `<span class="stg stg${r[8]}" style="opacity:.5">${r[8]}</span>→<span class="stg stg${r[7]}">${r[7]}</span>` : `<span class="stg stg${r[7]}">${r[7]}</span>`);
    h += `<tr><td class="mono" style="color:var(--ink3)">${n+1}</td><td class="nm l"><b>${esc(r[1])}</b><small class="mono">${esc(r[0])}</small></td><td class="ind l">${esc(inds[r[3]]||"")}</td>
      <td class="ctr"><span class="state ${DCLS[r[4]]}">${DSTATE[r[4]]}</span>${chg} <span class="mono" style="font-size:11px;color:var(--ink3)">${r[5]}일</span></td>
      <td class="ctr">${r[6]==null?"–":`<span class="state ${DCLS[r[6]]}">${DSTATE[r[6]]}</span>`}</td>
      <td class="ctr">${sg}</td>
      <td class="mono ${r[9]===8?"pos":""}">${r[9]==null?"–":r[9]+"/8"}</td>
      <td class="mono">${r[10]??"–"}</td><td class="mono">${r[11]==null?"–":fmt(r[11])+"%"}</td>` +
      r[14].map(g => `<td class="mono" style="${heat(g, 15)}">${g==null?"–":fmt(g)}</td>`).join("") +
      `<td class="mono">${money(r[13])}</td></tr>`;
  });
  if(rows.length > 600) h += `<tr><td colspan="20" class="ctr" style="color:var(--ink3)">상위 600종목만 표시. 검색이나 필터로 좁혀 볼 것.</td></tr>`;
  $("#stocks").innerHTML = h + "</tbody>";
}

/* ══ 3. 신호 검증 ══════════════════════════ */
async function renderSignal(){
  const SG = await tryJSON(`data/${MKT}/signals.json`);
  if(!SG){ $("#view").innerHTML = `<div class="card"><div class="empty-state">신호 검증 데이터가 아직 없음.</div></div>`; return; }
  const key = `${S.unit}|${S.freq}|${S.mode}|${S.weight}|${S.turn}`;
  const tb = SG.tables[key];
  if(!tb){ $("#view").innerHTML = `<div class="card"><div class="empty-state">이 조합의 표가 없음 (${esc(key)}).</div></div>`; return; }
  const hz = S.freq==="week" ? ["다음 1주","다음 4주"] : ["다음날","다음 5일"];
  const allM = [tb.h1.all.mean, tb.h2.all.mean];
  let h = `<thead><tr><th class="l" rowspan="2">판정</th>${hz.map(x => `<th class="g" colspan="5">${x} 시장 대비 (%p)</th>`).join("")}</tr>
    <tr>${[0,1].map(() => `<th class="lead">표본</th><th>평균</th><th>중앙값</th><th>승률</th><th>t</th>`).join("")}</tr></thead><tbody>`;
  for(const k of [...CATS, "all"]){
    const isAll = k==="all";
    h += `<tr class="${isAll?"base":""}"><td class="l">${isAll?"<b>전체 (기준선)</b>":`<span class="state ${k}" style="min-width:auto;padding:2px 8px">${CAT[k]}</span>`}</td>`;
    [tb.h1, tb.h2].forEach((t, j) => {
      const r = t[k] || {n:0};
      if(!r.n){ h += `<td class="lead mono">0</td><td colspan="4" class="ctr" style="color:var(--ink3)">표본 없음</td>`; return; }
      const ex = r.mean - (allM[j]||0);
      const sig = Math.abs(r.t||0) >= 2 && r.n >= 30;
      h += `<td class="lead mono">${r.n.toLocaleString()}</td><td class="mono" style="${isAll?"":heat(ex, 1.5)}"><b>${fmt(r.mean,2)}</b></td><td class="mono">${fmt(r.med,2)}</td><td class="mono">${r.hit?.toFixed(0)}%</td><td class="mono" style="${sig?"font-weight:700":"color:var(--ink3)"}">${r.t==null?"–":r.t.toFixed(1)}</td>`;
    });
    h += `</tr>`;
  }
  const unitTxt = S.unit==="sector" ? "섹터" : "산업(5종목 이상)";
  $("#view").innerHTML = `<div class="legend"><span class="lg">${unitTxt}</span><span class="lg">${S.freq==="week"?"주간 판정":"일간 판정"}</span><span class="lg">${S.mode==="sigma"?"변동성 σ":"고정 %p"}</span><span class="lg">${S.weight==="cw"?"시총가중":"동일가중"}</span><span class="lg">${S.turn==="tv"?"거래대금":"거래량"}</span>
      <span class="lg" style="border:0;background:none">기간 ${SG.from} ~ ${SG.to} (${SG.weeks}주)</span></div>
    <div class="card"><div class="scroll"><table class="sig">${h}</tbody></table></div></div>
    <div class="foot">평균 칸 색 = 전체 평균 대비 초과분(빨강 높음·파랑 낮음). t는 평균÷표준오차이고, |t|≥2·표본 30 이상이면 굵게 표시함. 기준값 조정은 반영되지 않고 기본값(일 ±1%p·1.1배, 주 ±2%p·1.05배, ±1σ)으로 집계됨.</div>
    <div class="warnbox"><b>읽을 때 주의</b><br>
      ① 기간이 2년 미만이고 같은 주의 업종들은 서로 상관돼 있어 실제 독립 표본은 표의 숫자보다 훨씬 적음.<br>
      ② ${hz[1]} 성과는 기간이 겹치는 관측치를 모두 썼으므로 t값이 부풀려져 있음. 방향 확인용으로만 볼 것.<br>
      ③ 거래비용·슬리피지 없음. 업종 바스켓을 그대로 사는 것을 가정함.<br>
      ④ 현재 유니버스로 과거를 계산해 생존 편향이 있음.<br>
      ⑤ 여러 조합을 바꿔 보다 보면 우연히 좋아 보이는 조합이 반드시 나옴. 한 조합만 보고 결론 내리지 말고, 시장·가중·단위를 바꿔도 같은 방향이 유지되는지 확인할 것.</div>`;
}

/* ── 이벤트 ─────────────────────────── */
document.querySelectorAll(".seg").forEach(g => g.addEventListener("click", e => {
  const b = e.target.closest("button"); if(!b) return;
  S[g.dataset.k] = b.dataset.v; save(); render();
}));
document.querySelectorAll("[data-t]").forEach(inp => inp.addEventListener("change", () => {
  const v = parseFloat(inp.value); if(isFinite(v)){ S[inp.dataset.t] = v; save(); render(); }
}));
$("#minn").addEventListener("change", e => { const v = parseInt(e.target.value,10); if(v>0){ S.minn = v; save(); render(); } });
$("#secf").addEventListener("change", e => { SECF = e.target.value; render(); });
$("#reset").onclick = () => { Object.assign(S, {dR:DEF.dR, wR:DEF.wR, zR:DEF.zR, dT:DEF.dT, wT:DEF.wT}); save(); render(); };
$("#week").onchange = e => openWeek(e.target.value);
$("#prev").onclick = () => openWeek(INDEX.weeks[INDEX.weeks.indexOf(WEEK)-1]);
$("#next").onclick = () => openWeek(INDEX.weeks[INDEX.weeks.indexOf(WEEK)+1]);
$("#mtabs").addEventListener("click", e => {
  const b = e.target.closest("button[data-m]"); if(!b || b.dataset.m===MKT) return;
  closeDrill(); sortCol = "week"; SECF = ""; rrgSel = null; NHDAY = null; nhF.label = ""; openMarket(b.dataset.m, WEEK);
});
$("#vtabs").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]"); if(!b) return;
  VIEW = b.dataset.v; closeDrill(); render();
});
$("#view").addEventListener("click", async e => {
  const t = e.target;
  if(VIEW==="weekly"){
    const wt = t.closest("[data-wkt]");
    if(wt){ wkTab = wt.dataset.wkt; const y = window.scrollY; await render(); window.scrollTo(0, y); }
    return;
  }
  if(VIEW==="newhigh"){
    const nb = t.closest("[data-nh]");
    if(nb){ const k = nb.dataset.nh; if(k==="cluster") nhF.cluster = !nhF.cluster; else nhF[k] = nb.dataset.nv; render(); return; }
    const nl = t.closest("[data-nhl]");
    if(nl && !t.closest("a")){ nhF.label = nhF.label===nl.dataset.nhl ? "" : nl.dataset.nhl; await render(); document.querySelector(".nhg")?.scrollIntoView({behavior:"smooth"}); return; }
    if(t.closest("[data-fs]")){ followSort = -followSort; render(); return; }
    return;
  }
  const tog = t.closest("[data-tog]");
  if(tog){ const k = tog.dataset.tog; expanded.has(k) ? expanded.delete(k) : expanded.add(k); render(); return; }
  const s = t.closest("th[data-sort]");
  if(s){ sortCol = s.dataset.sort==="week" ? "week" : +s.dataset.sort; render(); return; }
  const xs = t.closest("th[data-xs]");
  if(xs){ crossSort = xs.dataset.xs; render(); return; }
  const xm = t.closest("td[data-xm]");
  if(xm){
    const {xm:m, key, kind} = xm.dataset;
    VIEW = "map"; if(kind==="industry") S.unit = "industry";
    if(m!==MKT) await openMarket(m, WEEK); else render();
    openDrill(kind, key, "week"); return;
  }
  const cell = t.closest("td[data-kind]");
  if(cell && VIEW==="map"){ openDrill(cell.dataset.kind, cell.dataset.key, cell.dataset.day==="week" ? "week" : +cell.dataset.day); return; }
  const rg = t.closest("[data-rg]");
  if(rg){ rrgSel = rrgSel===rg.dataset.rg ? null : rg.dataset.rg; render(); return; }
  const ts = t.closest("[data-tsec]");
  if(ts){ openTrendDrill({sector: ts.dataset.tsec}); return; }
  const mx = t.closest("td[data-mx]");
  if(mx && !mx.classList.contains("z")){ const [d,w] = mx.dataset.mx.split("|"); openTrendDrill({d, w}); return; }
  const tq = t.closest("[data-tq]");
  if(tq){ openTrendDrill({f: tq.dataset.tq}); return; }
});
$("#stocks").addEventListener("click", e => {
  const th = e.target.closest("th[data-col]"); if(!th) return;
  const col = th.dataset.col;
  dSort = dSort.col===col ? {col, dir:-dSort.dir} : {col, dir: (col==="name"||col==="ind") ? 1 : -1};
  drill?.mode==="trend" ? renderTrendDrill() : renderDrill();
});
$("#close").onclick = closeDrill;
$("#sheet").addEventListener("click", e => { if(e.target.id==="sheet") closeDrill(); });
document.addEventListener("keydown", e => { if(e.key==="Escape" && drill) closeDrill(); });

/* ══ 10. 매크로 ════════════════════════════ */
const KUNIT = {pct:"%", bp:"bp", pt:"pt"};
function mchg(kind, now, then){
  if(now==null || then==null) return null;
  return kind==="pct" ? (then ? (now/then-1)*100 : null) : kind==="bp" ? (now-then)*100 : now-then;
}
const mfmt = (v, kind) => v==null ? "–" : `${v>0?"+":v<0?"−":""}${Math.abs(v).toFixed(kind==="bp"?0:kind==="pt"?2:2)}${KUNIT[kind]}`;
const mscale = {pct:6, bp:40, pt:5};
function mlast(it){
  const v = it.last; if(v==null) return "–";
  if(it.kind==="bp") return v.toFixed(2)+"%";
  const a = Math.abs(v);
  return a >= 1000 ? Math.round(v).toLocaleString() : a >= 100 ? v.toFixed(1) : v.toFixed(2);
}
function mspark(arr, w=120, h=28){
  const v = (arr||[]).filter(x => x!=null); if(v.length < 3) return "";
  const lo = Math.min(...v), hi = Math.max(...v), r = hi-lo || 1;
  const d = v.map((x,i) => `${i?"L":"M"}${(i/(v.length-1)*w).toFixed(1)},${(h-2-(x-lo)/r*(h-4)).toFixed(1)}`).join("");
  return `<svg class="mspark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"><path d="${d}" fill="none" stroke="var(--accent)" stroke-width="1.3"/></svg>`;
}
function macroWeek(M, week){
  // 주간 요약용: 그 주(월요일 키) 마지막 값 vs 직전 주 마지막 값
  const out = {};
  for(const g of M.groups) for(const it of g.items){
    const ks = Object.keys(it.wk||{}).sort(), i = ks.indexOf(week);
    if(i > 0) out[it.sym] = {...it, w: mchg(it.kind, it.wk[ks[i]], it.wk[ks[i-1]]), wv: it.wk[ks[i]]};
  }
  return out;
}
async function renderMacro(){
  const M = await tryJSON("data/macro.json");
  if(!M){ $("#view").innerHTML = `<div class="card"><div class="empty-state">매크로 데이터가 아직 없음. 업종 심리 지도 갱신이 한 번 돌면 생성됨.</div></div>`; return; }
  const cols = [["d1","1일"],["w1","1주"],["m1","1개월"],["m3","3개월"],["ytd","연초 대비"],["y1","1년"]];
  let h = `<div class="bar" style="margin-top:0"><span class="tag">갱신 ${esc(M.generated)}</span>${M.missing?.length?`<span class="tag" title="${esc(M.missing.join(", "))}">못 받은 지표 ${M.missing.length}개</span>`:""}</div>
    <div class="mac-grid">`;
  for(const g of M.groups){
    h += `<div class="card mac-card"><h3>${esc(g.name)}</h3><div class="scroll"><table class="tbl mac"><thead><tr><th class="l">지표</th><th>현재</th>${cols.map(c => `<th>${c[1]}</th>`).join("")}<th class="l">52주 위치</th><th class="l">6개월</th></tr></thead><tbody>`;
    for(const it of g.items){
      const sc = mscale[it.kind];
      h += `<tr><td class="l"><b>${esc(it.name)}</b><small>${esc(it.sym)} · ${esc(md(it.date))}</small></td><td class="mono"><b>${mlast(it)}</b></td>` +
        cols.map(([k]) => { const v = it.chg[k]; return `<td class="mono" style="${heat(v, k==="d1"?sc/3:k==="w1"?sc/1.5:sc*1.5)}">${mfmt(v, it.kind)}</td>`; }).join("") +
        `<td class="l"><div class="pos52" title="${esc(`1년 범위 ${it.lo52} ~ ${it.hi52}`)}"><i style="left:${it.pos52??50}%"></i></div></td><td class="l">${mspark(it.spark)}</td></tr>`;
    }
    h += `</tbody></table></div></div>`;
  }
  h += `</div><p class="foot">출처: yfinance(야후 파이낸스) 종가, 미 2년·10년−2년·신용 스프레드는 FRED(ICE BofA OAS). 선물은 근월물 연속, 장 마감 시각이 지표마다 달라 같은 날짜라도 시점이 다를 수 있음.</p>`;
  $("#view").innerHTML = h;
}

/* ══ 9. 주간 요약 ══════════════════════════ */
const pc = (x, d=2) => x==null ? "–" : `${x>0?"+":x<0?"−":""}${Math.abs(x).toFixed(d)}%`;
const pcls = x => x==null ? "" : x>0 ? "pos" : x<0 ? "neg" : "";
function hbars(items, {val, label, sub, max, fmtv = v => pc(v), cls = ""}){
  if(!items.length) return `<div class="empty-state" style="padding:24px">해당 없음</div>`;
  const mx = max || Math.max(...items.map(x => Math.abs(val(x)||0)), 0.01);
  return `<div class="hb ${cls}">` + items.map(x => { const v = val(x) || 0, w = Math.min(Math.abs(v)/mx, 1)*100;
    return `<div class="hb-r"><div class="hb-l"><b>${esc(label(x))}</b>${sub?`<small>${sub(x)}</small>`:""}</div>
      <div class="hb-b"><i class="${v>=0?"up":"dn"}" style="width:${w.toFixed(1)}%"></i></div><div class="hb-v mono ${pcls(v)}">${fmtv(v)}</div></div>`; }).join("") + `</div>`;
}
function dayBars(b, scale){
  const days = b.days, bench = b.bench[0], W0 = 300, H0 = 150, pad = 18, bw = (W0-20)/days.length;
  const y = v => H0/2 - v/scale*(H0/2-pad);
  let s = `<svg viewBox="0 0 ${W0} ${H0}" class="wkbars">`;
  for(const g of [scale, scale/2, 0, -scale/2, -scale]) s += `<line x1="16" x2="${W0}" y1="${y(g)}" y2="${y(g)}" stroke="${g?"var(--line2)":"var(--ink3)"}" stroke-width="${g?1:.8}"/><text x="13" y="${y(g)+3}" text-anchor="end" font-size="8" fill="var(--ink3)">${g>0?"+":""}${+g.toFixed(1)}</text>`;
  days.forEach((d,i) => {
    const x = 20 + i*bw + bw*.2, w = bw*.6, v = bench?.days?.[d], r = b.recon.days?.[d];
    if(v!=null){ const t = Math.max(-scale, Math.min(scale, v)); s += `<rect x="${x}" y="${Math.min(y(0),y(t))}" width="${w}" height="${Math.abs(y(t)-y(0))}" fill="${v>=0?"var(--up)":"var(--dn)"}" opacity=".85"><title>${esc(`${d} ${bench.name} ${pc(v)}`)}</title></rect>`;
      s += `<text x="${x+w/2}" y="${v>=0? y(t)-3 : y(t)+9}" text-anchor="middle" font-size="8" class="mono" fill="var(--ink2)">${v>0?"+":""}${v.toFixed(2)}</text>`; }
    if(r!=null){ const t = Math.max(-scale, Math.min(scale, r)); s += `<circle cx="${x+w/2}" cy="${y(t)}" r="2.6" fill="var(--ink)" stroke="var(--panel)" stroke-width="1"><title>${esc(`${d} 재구성 ${pc(r)}`)}</title></circle>`; }
    s += `<text x="${x+w/2}" y="${H0-2}" text-anchor="middle" font-size="8" fill="var(--ink3)">${md(d)} ${WD[new Date(d+"T00:00:00Z").getUTCDay()-1]||""}</text>`;
  });
  return s + `</svg>`;
}

async function renderWeekly(){
  const WI = await tryJSON("data/weekly/index.json");
  if(!WI || !WI.weeks?.length){ $("#view").innerHTML = `<div class="card"><div class="empty-state">주간 요약이 아직 없음. 업종 심리 지도 갱신이 한 번 돌면 생성됨.</div></div>`; return; }
  if(!WKSEL || !WI.weeks.includes(WKSEL)) WKSEL = WI.weeks.includes(WEEK) ? WEEK : WI.weeks[WI.weeks.length-1];
  setHash();
  const R = await getJSON(`data/weekly/${WKSEL}.json`);
  const ms = R.markets;
  const MAC = await tryJSON("data/macro.json");
  const MW = MAC ? macroWeek(MAC, WKSEL) : {};
  const fx = {kr: MW["KRW=X"]?.w, jp: MW["JPY=X"]?.w};
  const main = b => b.bench[0]?.week ?? b.recon.cw;
  const scale = Math.max(3, Math.ceil(Math.max(...ms.flatMap(m => [...Object.values(R.blocks[m].bench[0]?.days||{}), ...Object.values(R.blocks[m].recon.days||{})]).filter(v => v!=null).map(Math.abs), 0)));
  const opts = WI.weeks.slice().reverse().map(w => `<option value="${w}"${w===WKSEL?" selected":""}>${md(w)}(월) 주</option>`).join("");
  let h = `<div class="bar" style="margin-top:0"><div class="grp"><label>주</label><select id="wksel">${opts}</select></div><span class="tag">갱신 ${esc(R.generated||"")}</span></div>
    <div class="wk-kicker">숫자로 본 한 주</div><h2 class="wk-head">${esc(R.headline||"")}</h2>
    <p class="sdesc">막대는 각 시장 실제 지수(${ms.map(m => esc(R.blocks[m].bench[0]?.name||"재구성")).join("·")})의 요일별 등락, 점은 이 사이트 유니버스로 재구성한 시총가중 등락. 세 나라를 같은 눈금(±${scale}%)에 그림.</p>
    <div class="wk-cards">`;
  for(const m of ms){
    const b = R.blocks[m], v = main(b), sz = b.size || [];
    const row = (l, x, cls="") => `<tr><td class="l">${l}</td><td class="mono ${cls}">${x}</td></tr>`;
    h += `<div class="card wk-card"><div class="wk-mk"><span class="tag">${m.toUpperCase()}</span> <b>${esc(b.label)}</b></div>
      <div class="wk-big mono ${pcls(v)}">${pc(v)}</div><div class="wk-sub">${esc(b.bench[0]?.name || "재구성 (실제 지수 없음)")} 주간</div>
      ${dayBars(b, scale)}
      <table class="wk-t">${row("벤치마크 (재구성 시총가중)", pc(b.recon.cw), pcls(b.recon.cw))}${row("동일가중", pc(b.recon.ew), pcls(b.recon.ew))}
        ${row("가운데 종목", pc(b.median), pcls(b.median))}${row("주간 오른 종목", b.up_pct==null?"–":b.up_pct+"%")}
        ${sz[0]?row(`${esc(sz[0].label)} 묶음`, pc(sz[0].cw), pcls(sz[0].cw)):""}${row("대상 종목 수", b.n.toLocaleString())}
        ${b.bench.slice(1).map(x => row(esc(x.name), pc(x.week), pcls(x.week))).join("")}
        ${fx[m]!=null && v!=null ? row(`달러 기준 <small>(${m==="kr"?"원":"엔"}/달러 ${pc(fx[m])})</small>`, pc(((1+v/100)/(1+fx[m]/100)-1)*100), pcls(((1+v/100)/(1+fx[m]/100)-1)*100)) : ""}
        ${(() => { const br = b.breadth || {}; let x = "";
          if(br.a50!=null) x += row("50일선 위 종목", `${br.a50.toFixed(0)}% <small class="${pcls(br.a50_prev!=null?br.a50-br.a50_prev:null)}">${br.a50_prev!=null?fmt(br.a50-br.a50_prev,0)+"p":""}</small>`);
          if(br.nhl!=null) x += row("52주 신고가 − 신저가 (주)", `${br.nhl>0?"+":""}${br.nhl}`, pcls(br.nhl));
          if(br.conc!=null) x += row("거래대금 상위 10 몫", br.conc.toFixed(1)+"%");
          if(br.tv!=null) x += row("시장 거래대금 (20일 평균 대비)", br.tv.toFixed(2)+"배");
          return x; })()}</table>
      <ul class="wk-notes">${(b.notes||[]).map(t => `<li>${esc(t)}</li>`).join("")}</ul></div>`;
  }
  h += `</div>`;

  // 이번 주 매크로
  const KEYM = [["KRW=X","원/달러"],["JPY=X","엔/달러"],["DX-Y.NYB","달러인덱스"],["^TNX","미 10년"],["BAMLH0A0HYM2","HY 스프레드"],["^VIX","VIX"],["CL=F","WTI"],["GC=F","금"],["HG=F","구리"],["BTC-USD","비트코인"]];
  const chips = KEYM.filter(([s]) => MW[s]).map(([s,l]) => { const x = MW[s];
    return `<div class="mchip"><span>${l}</span><b class="mono ${pcls(x.w)}">${mfmt(x.w, x.kind)}</b><small class="mono">${x.kind==="bp"?x.wv.toFixed(2)+"%":Math.abs(x.wv)>=1000?Math.round(x.wv).toLocaleString():x.wv.toFixed(2)}</small></div>`; }).join("");
  if(chips) h += `<div class="wk-kicker" style="margin-top:24px">이번 주 매크로</div><div class="mchips">${chips}</div><p class="foot" style="margin-top:6px">주간 마지막 값 대비 전주 마지막 값. 금리·스프레드는 bp, VIX 는 포인트. 전체는 '매크로' 탭.</p>`;

  // 3국 공통 업종
  const C = R.common, nm = C.markets.length;
  if(nm >= 2){
    const sub = x => C.markets.map(m => `${SHORTM[m]} ${pc(x.by[m],1)}`).join(" · ");
    h += `<div class="wk-kicker" style="margin-top:28px">${nm}국 공통 업종</div><p class="sdesc">${nm}국 모두에서 시장보다 강하거나 약했던 산업(각 시장 ${3}종목 이상). 막대는 ${nm}국 시장 대비 수익률의 평균(%p).</p>
      <div class="wk-two"><div class="card wk-pane"><h3>${nm}국 공통 강세</h3>${hbars(C.strong, {val:x=>x.avg, label:x=>x.name, sub, fmtv:v=>pc(v)+"p"})}</div>
      <div class="card wk-pane"><h3>${nm}국 공통 약세</h3>${hbars(C.weak, {val:x=>x.avg, label:x=>x.name, sub, fmtv:v=>pc(v)+"p"})}</div></div>`;
  }

  // 테마 바스켓
  const TH = R.themes || [];
  if(TH.length){
    const shown = TH.length > 20 ? [...TH.slice(0,10), null, ...TH.slice(-10)] : TH;
    h += `<div class="wk-kicker" style="margin-top:28px">내 테마 바스켓</div><p class="sdesc"><code>data/newhigh/labels.csv</code> 의 테마 라벨별 주간 동일가중 수익률. 유니버스(시총 하한 이상)에 있는 종목만 계산하므로 '계산/등록' 종목 수를 같이 봐야 함. 상위·하위 10개.</p>
      <div class="card"><div class="scroll"><table class="tbl"><thead><tr><th class="l">테마</th><th>계산/등록</th>${ms.map(m => `<th>${SHORTM[m]}</th>`).join("")}<th>평균</th><th>중앙값</th><th>오른 종목</th></tr></thead><tbody>` +
      shown.map(t => t===null ? `<tr><td colspan="${6+ms.length}" class="ctr" style="color:var(--ink3)">⋯ ${TH.length-20}개 생략 ⋯</td></tr>` :
        `<tr><td class="l"><b>${esc(t.label)}</b></td><td class="mono">${t.n}/${t.listed}</td>` + ms.map(m => { const x = t.by[m]; return `<td class="mono ${x?pcls(x.avg):""}">${x?`${pc(x.avg,1)} <small style="color:var(--ink3)">${x.n}</small>`:"·"}</td>`; }).join("") +
        `<td class="mono ${pcls(t.avg)}" style="${heat(t.avg, 8)}"><b>${pc(t.avg)}</b></td><td class="mono ${pcls(t.med)}">${pc(t.med)}</td><td class="mono">${t.up}%</td></tr>`).join("") +
      `</tbody></table></div></div>`;
  }

  // 시장 상세
  if(!ms.includes(wkTab)) wkTab = ms.includes(MKT) ? MKT : ms[0];
  const b = R.blocks[wkTab], cur = b.currency;
  h += `<div class="wk-detail-h"><div class="wk-kicker" style="margin:0">시장 상세</div><div class="mtabs" style="margin:0">${ms.map(m => `<button data-wkt="${m}" class="${m===wkTab?"on":""}">${R.blocks[m].flag} ${esc(R.blocks[m].label)}</button>`).join("")}</div></div>`;
  const mvsub = x => `${esc(x.ind||"")} · 시총 ${moneyDelta(x.dmcap)}${cur==="달러"?"달러":cur==="원"?"원":"엔"}`;
  h += `<div class="wk-two"><div class="card wk-pane"><h3>시가총액을 가장 많이 잃은 종목 <small>막대 = 주간 수익률</small></h3>${hbars(b.movers.down, {val:x=>x.week, label:x=>x.name, sub:mvsub})}</div>
    <div class="card wk-pane"><h3>시가총액을 가장 많이 늘린 종목 <small>막대 = 주간 수익률</small></h3>${hbars(b.movers.up, {val:x=>x.week, label:x=>x.name, sub:mvsub})}</div></div>`;
  const isub = x => `${x.n}종목 · 시장 대비 ${pc(x.rel)}p`;
  h += `<div class="wk-two"><div class="card wk-pane"><h3>시장보다 강했던 산업 <small>주간 수익률(막대)</small></h3>${hbars(b.ind_strong, {val:x=>x.ret, label:x=>x.name, sub:isub})}</div>
    <div class="card wk-pane"><h3>시장보다 약했던 산업 <small>주간 수익률(막대)</small></h3>${hbars(b.ind_weak, {val:x=>x.ret, label:x=>x.name, sub:isub})}</div></div>`;
  // 지수 기여도
  const CB = b.contrib;
  if(CB && CB.total!=null){
    const csub = x => `${esc(x.ind||"")} · 비중 ${x.w.toFixed(2)}% · 주간 ${pc(x.week,1)}`;
    const share = (t5, tot) => tot ? ` (${Math.round(t5/tot*100)}%)` : "";
    h += `<div class="wk-kicker" style="margin-top:24px">지수 기여도</div><p class="sdesc">재구성 시총가중 ${pc(CB.total)}p를 종목별로 나눈 것. 기여 = 주 시작 시총 비중 × 주간 수익률. 끌어내린 상위 5 합계 ${pc(CB.top5_down)}p${CB.total<0?share(CB.top5_down, CB.total):""}, 끌어올린 상위 5 합계 ${pc(CB.top5_up)}p.</p>
      <div class="wk-two"><div class="card wk-pane"><h3>지수를 끌어내린 종목</h3>${hbars(CB.down, {val:x=>x.c, label:x=>x.name, sub:csub, fmtv:v=>pc(v)+"p"})}</div>
      <div class="card wk-pane"><h3>지수를 끌어올린 종목</h3>${hbars(CB.up, {val:x=>x.c, label:x=>x.name, sub:csub, fmtv:v=>pc(v)+"p"})}</div></div>
      <div class="card wk-pane" style="margin-top:12px"><h3>섹터별 기여 <small>합계 ${pc(CB.total)}p</small></h3>${hbars(CB.sectors.slice().sort((a,b)=>a.c-b.c), {val:x=>x.c, label:x=>x.name, fmtv:v=>pc(v)+"p", cls:"two"})}</div>`;
  }

  // 흐름: 지속·로테이션·연속·신고가
  h += `<div class="wk-kicker" style="margin-top:24px">흐름</div>`;
  const PS = b.persist;
  if(PS){
    const psub = x => `${x.n}종목 · 지난주 ${pc(x.prev,1)}p → 이번 주 ${x.now==null?"–":pc(x.now,1)+"p"}`;
    h += `<div class="wk-two"><div class="card wk-pane"><h3>지난주 강했던 산업의 이번 주 <small>${PS.keep_strong}/${PS.strong.length} 지속</small></h3>${hbars(PS.strong, {val:x=>x.now, label:x=>x.name, sub:psub, fmtv:v=>pc(v)+"p"})}</div>
      <div class="card wk-pane"><h3>지난주 약했던 산업의 이번 주 <small>${PS.keep_weak}/${PS.weak.length} 지속</small></h3>${hbars(PS.weak, {val:x=>x.now, label:x=>x.name, sub:psub, fmtv:v=>pc(v)+"p"})}</div></div>`;
  }
  const SU = b.streak_up || [], SD = b.streak_down || [];
  if(SU.length || SD.length){
    const ssub = x => `${x.n}종목 · 누적 ${pc(x.cum,1)}p · 이번 주 ${pc(x.now,1)}p`;
    h += `<div class="wk-two"><div class="card wk-pane"><h3>연속 시장 상회 <small>3주 이상</small></h3>${hbars(SU, {val:x=>x.weeks, label:x=>x.name, sub:ssub, fmtv:v=>v+"주", max:Math.max(6, ...SU.map(x=>x.weeks))})}</div>
      <div class="card wk-pane"><h3>연속 시장 하회 <small>3주 이상</small></h3>${hbars(SD, {val:x=>-x.weeks, label:x=>x.name, sub:ssub, fmtv:v=>(-v)+"주", max:Math.max(6, ...SD.map(x=>x.weeks))})}</div></div>`;
  }
  const MV = b.moves || [];
  if(MV.length){
    const qc = {"선도":"var(--s2)","약화":"var(--s3)","소외":"var(--s4)","개선":"var(--dn)"};
    h += `<div class="card wk-pane" style="margin-top:12px"><h3>로테이션 분면 이동 <small>전주 → 이번 주 · 산업 단위 · 시총가중</small></h3><div class="rmoves">` +
      MV.map(x => `<div class="rmove"><div class="rmove-h"><span class="qd" style="background:${qc[x.from]}"></span>${esc(x.from)} → <span class="qd" style="background:${qc[x.to]}"></span><b>${esc(x.to)}</b> <small>${x.items.length}</small></div>
        <div class="rmove-l">${x.items.slice(0,8).map(i => `<span>${esc(i.name)} <small class="mono ${pcls(i.rc)}">${pc(i.rc,1)}p</small></span>`).join("")}${x.items.length>8?`<span style="color:var(--ink3)">외 ${x.items.length-8}</span>`:""}</div></div>`).join("") + `</div></div>`;
  }
  const NH = b.newhigh;
  if(NH && NH.n){
    const dd = Object.entries(NH.days);
    const mx = Math.max(1, ...dd.map(([,v])=>v));
    h += `<div class="card wk-pane" style="margin-top:12px"><h3>신고가 주간 결산 <small>${NH.n}종목 (역대 ${NH.ath} · 52주 ${NH.w52}) · 신고가 기록이 있는 날만</small></h3>
      <div class="nhw"><div class="nhw-d">${dd.map(([d,v]) => `<div><i style="height:${(v/mx*48).toFixed(0)}px"></i><b class="mono">${v}</b><small>${md(d)}</small></div>`).join("")}</div>
      <div style="min-width:0;flex:1">${hbars(NH.labels, {val:x=>x.n, label:x=>x.label, sub:x=>esc(x.names.join(", "))+(x.repeat?` · 2회+ ${x.repeat}`:""), fmtv:v=>v+"종목"})}</div></div></div>`;
  }

  h += `<div class="card wk-pane" style="margin-top:12px"><h3>규모별 주간 수익률</h3><div class="scroll"><table class="tbl"><thead><tr><th class="l">묶음</th><th>주간</th><th>시장 대비</th><th>오른 종목</th></tr></thead><tbody>` +
    (b.size||[]).map(s => `<tr><td class="l">${esc(s.label)} <small style="color:var(--ink3)">${s.n}</small></td><td class="mono ${pcls(s.cw)}">${pc(s.cw)}</td><td class="mono ${pcls(s.rel)}">${s.rel==null?"–":pc(s.rel)}</td><td class="mono">${s.up==null?"–":s.up+"%"}</td></tr>`).join("") +
    `</tbody></table></div><p class="sdesc" style="margin:8px 0 0">규모는 연초 시총 순위. 시장 대비 = 묶음 수익률 − 재구성 시총가중 수익률(${pc(b.recon.cw)}).</p></div>`;
  h += `<div class="card wk-pane" style="margin-top:12px"><h3>업종·테마 ETF 주간 <small>실제 ETF 종가 · ${b.etfs.length}개</small></h3>${hbars(b.etfs, {val:x=>x.week, label:x=>x.name, sub:x=>esc(x.sym), cls:"two"})}</div>`;
  if(wkTab==="kr") h += `<p class="foot">투자자별 순매수(외국인·기관·개인)는 아직 연결된 데이터 소스가 없어 빠져 있음.</p>`;
  h += `<p class="foot">재구성 지수는 이 사이트 유니버스(시총 하한 이상 보통주) 기준이라 실제 지수와 다름. 실제 지수·ETF 는 yfinance 종가(배당 조정)이며 받지 못한 날은 비어 있음.</p>`;
  $("#view").innerHTML = h;
  $("#wksel").onchange = e => { WKSEL = e.target.value; render(); };
}
const SHORTM = {us:"미", jp:"일", kr:"한"};

/* ══ 8. 신고가 ═════════════════════════════ */
const KIND = {ATH:"역대", "52W":"52주"};
function nhLinks(st){
  const c = encodeURIComponent(st.code), ex = st.exchange ? `${st.exchange}:` : "";
  const tv = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(ex+st.code)}`;
  const info = MKT==="kr" ? `https://finance.naver.com/item/main.naver?code=${c}` :
               MKT==="jp" ? `https://finance.yahoo.co.jp/quote/${c}.T` : `https://finance.yahoo.com/quote/${c}`;
  const disc = MKT==="kr" ? `https://finance.naver.com/item/news_notice.naver?code=${c}` :
               MKT==="jp" ? `https://kabutan.jp/stock/news?code=${c}` : `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${c}&type=8-K`;
  const a = (u,t) => `<a href="${esc(u)}" target="_blank" rel="noopener">${t}</a>`;
  return `${a(tv,"차트")} · ${a(info, MKT==="kr"?"네이버":"Yahoo")} · ${a(disc, MKT==="kr"?"공시":MKT==="jp"?"kabutan":"EDGAR")}`;
}
function nhChart(ch, w=300, h=110){
  if(!ch || !ch.c || ch.c.length < 10) return `<div class="nhc-empty">차트 데이터 없음</div>`;
  const c = ch.c, n = c.length, st = ch.step || 2;
  const ma = k => { const m = Math.max(1, Math.round(k/st)); return c.map((_,i) => i+1 < m ? null : c.slice(i+1-m, i+1).reduce((a,b)=>a+b,0)/m); };
  const show = Math.min(n, Math.round(252/st));               // 최근 1년만 그림 (이평은 앞 구간으로 계산)
  const from = n - show;
  const lines = [{v:c, col:"var(--ink)", w:1.4}, {v:ma(20), col:"var(--up)", w:.9}, {v:ma(50), col:"var(--warn)", w:.9}, {v:ma(200), col:"var(--dn)", w:.9}];
  const vis = lines.flatMap(l => l.v.slice(from).filter(x => x!=null));
  if(ch.p52) vis.push(ch.p52);
  let lo = Math.min(...vis), hi = Math.max(...vis); const pad = (hi-lo)*.06 || 1; lo -= pad; hi += pad;
  const X = i => (i-from)/(show-1)*(w-6)+3, Y = v => h-4-(v-lo)/(hi-lo)*(h-8);
  let s = `<svg viewBox="0 0 ${w} ${h}" class="nhc" preserveAspectRatio="none">`;
  if(ch.p52) s += `<line x1="0" x2="${w}" y1="${Y(ch.p52).toFixed(1)}" y2="${Y(ch.p52).toFixed(1)}" stroke="var(--ink3)" stroke-dasharray="3 3" stroke-width="1"/>`;
  for(const l of lines.slice(1).concat(lines.slice(0,1))){
    let d = ""; for(let i = from; i < n; i++){ const v = l.v[i]; if(v==null) continue; d += `${d?"L":"M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; }
    if(d) s += `<path d="${d}" fill="none" stroke="${l.col}" stroke-width="${l.w}" vector-effect="non-scaling-stroke"/>`;
  }
  s += `<circle cx="${X(n-1).toFixed(1)}" cy="${Y(c[n-1]).toFixed(1)}" r="3" fill="var(--up)"/>`;
  return s + `</svg>`;
}
function nhMat(list, cls){
  if(!list || !list.length) return "";
  return list.map(x => `<li class="${cls}"><a href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a> <span>${esc(x.s||"")} ${esc(md(x.d||"----------"))}</span></li>`).join("");
}

async function renderNewhigh(){
  const NI = await tryJSON(`data/${MKT}/newhigh/index.json`);
  if(!NI || !NI.days || !NI.days.length){
    $("#view").innerHTML = `<div class="card"><div class="empty-state">신고가 기록이 아직 없음. new-highs 워크플로가 한 번 실행되면(평일 07:20·16:20 자동, 또는 Actions에서 수동 실행) 표시됨.</div></div>`;
    return;
  }
  if(!NHDAY || !NI.days.includes(NHDAY)) NHDAY = NI.days[NI.days.length-1];
  setHash();
  const D = await getJSON(`data/${MKT}/newhigh/${NHDAY}.json`);
  const cur = INDEX?.currency || {us:"달러", kr:"원", jp:"엔"}[MKT];
  const cl = D.clusters || [], clSet = new Set(cl.map(c => c.label));
  const perf = D.perf || {};
  const labelsAll = [...new Set(D.stocks.map(s => s.label))];
  if(nhF.label && !labelsAll.includes(nhF.label)) nhF.label = "";
  let stocks = D.stocks.filter(s => (nhF.kind==="all" || s.kind===nhF.kind) && (!nhF.label || s.label===nhF.label) && (!nhF.cluster || clSet.has(s.label)));

  // 컨트롤
  const dayOpts = NI.days.slice().reverse().map(d => `<option value="${d}"${d===NHDAY?" selected":""}>${d}</option>`).join("");
  const chip = (k,v,l) => `<button class="chipb${nhF[k]===v?" on":""}" data-nh="${k}" data-nv="${v}">${l}</button>`;
  const nATH = D.stocks.filter(s => s.kind==="ATH").length;
  let h = `<div class="bar" style="margin-top:0">
    <div class="grp"><label>날짜</label><select id="nhday">${dayOpts}</select></div>
    <div class="filters">${chip("kind","all",`전체 ${D.stocks.length}`)}${chip("kind","ATH",`🏆 역대 ${nATH}`)}${chip("kind","52W",`📈 52주 ${D.stocks.length-nATH}`)}
      <button class="chipb${nhF.cluster?" on":""}" data-nh="cluster">🔥 군집만</button></div>
    <div class="grp"><label>라벨</label><select id="nhlab"><option value="">전체</option>${labelsAll.map(l => `<option${l===nhF.label?" selected":""}>${esc(l)}</option>`).join("")}</select></div>
  </div>`;

  // 군집 표
  if(cl.length){
    h += `<h2 class="sh" style="margin-top:6px">🔥 군집 <span class="tag">같은 라벨 ${3}종목 이상 또는 5일 누적 6종목 이상</span></h2>
      <div class="card"><div class="scroll"><table class="tbl"><thead><tr><th class="l">라벨</th><th>오늘</th><th>5일</th><th>20일</th><th class="l">업종 흐름 (업종 심리 지도)</th><th class="l">재료 (공시·뉴스 첫 항목)</th><th>신고가 이후</th></tr></thead><tbody>`;
    for(const c of cl){
      const ss = D.stocks.filter(s => s.label===c.label);
      const f = ss.flatMap(s => (s.filings||[]).slice(0,1).map(x => ({...x, nm:s.name, k:"공시"})))[0] ||
                ss.flatMap(s => (s.news||[]).slice(0,1).map(x => ({...x, nm:s.name, k:"뉴스"})))[0];
      const cx = c.context;
      const ctx = cx ? `${esc(cx.industry)} ${cx.rc!=null?fmt(cx.rc)+"%p":""}${cx.quad?` · <b>${esc(cx.quad)}</b>`:""}${cx.up_weeks>=2?` · ${cx.up_weeks}주 연속 상회`:""}` : `<span style="color:var(--ink3)">–</span>`;
      const pf = perf[c.label];
      h += `<tr class="click" data-nhl="${esc(c.label)}"><td class="l"><b>${esc(c.label)}</b></td><td class="mono"><b>${c.n}</b></td><td class="mono">${c.n5}</td><td class="mono">${c.n20}</td>
        <td class="l" style="white-space:normal;min-width:180px">${ctx}</td>
        <td class="l" style="white-space:normal;min-width:240px">${f?`<span style="color:var(--ink3)">${f.k} ${esc(f.nm)}:</span> <a href="${esc(f.u)}" target="_blank" rel="noopener">${esc(f.t)}</a>`:`<span style="color:var(--ink3)">재료 미확인</span>`}</td>
        <td class="mono">${pf?`<span class="${pf.med>=0?"pos":"neg"}">${fmt(pf.med)}%</span> <span style="color:var(--ink3);font-size:11px">${pf.n}건·${pf.hit}%↑</span>`:"–"}</td></tr>`;
    }
    h += `</tbody></table></div></div>`;
  }

  // 라벨 × 날짜 히트맵 (최근 20 기록일)
  const days = Object.keys(NI.counts).sort().slice(-20);
  const tot = {};
  days.forEach(d => Object.entries(NI.counts[d]).forEach(([l,n]) => tot[l] = (tot[l]||0)+n));
  const hl = Object.keys(tot).filter(l => tot[l] >= 2).sort((a,b) => tot[b]-tot[a]).slice(0, 25);
  if(hl.length && days.length > 1){
    const mx = Math.max(...hl.flatMap(l => days.map(d => NI.counts[d][l]||0)));
    h += `<h2 class="sh">라벨별 신고가 추이 <span class="tag">최근 ${days.length} 기록일 · 누적 2종목 이상</span></h2>
      <div class="card"><div class="scroll"><table class="tbl strip"><thead><tr><th class="l">라벨</th>${days.map(d => `<th class="c" style="padding:8px 2px;font-size:11px">${md(d)}</th>`).join("")}<th>합계</th></tr></thead><tbody>` +
      hl.map(l => `<tr class="click" data-nhl="${esc(l)}"><td class="l"><b>${esc(l)}</b></td>` + days.map(d => { const v = NI.counts[d][l]||0;
        return `<td class="s" style="${v?`background:rgba(209,52,74,${(.15+.6*v/mx).toFixed(2)})`:""}" title="${esc(`${d} · ${l} ${v}종목`)}">${v||""}</td>`; }).join("") + `<td class="mono">${tot[l]}</td></tr>`).join("") +
      `</tbody></table></div></div>`;
  }

  // 종목 카드 (라벨별, 군집 먼저)
  const groups = {};
  stocks.forEach(s => (groups[s.label] = groups[s.label] || []).push(s));
  const gorder = Object.keys(groups).sort((a,b) => (clSet.has(b)-clSet.has(a)) || groups[b].length-groups[a].length || Math.max(...groups[b].map(s=>s.change))-Math.max(...groups[a].map(s=>s.change)));
  h += `<h2 class="sh">종목 <span class="tag">${stocks.length}종목 · ${D.day}</span></h2>
    <p class="sdesc">차트: 최근 1년 종가(검정), 20·50·200일선(빨강·주황·파랑), 점선 = 직전 52주 고점. 뉴스·공시는 최근 ${3}일, 제목과 링크만 표시함. 재료가 없으면 수급·순환매일 가능성도 있음.</p>`;
  for(const g of gorder){
    const ss = groups[g].sort((a,b) => b.change-a.change);
    h += `<div class="nhg"><div class="nhg-h"><b>${esc(g)}</b> <span>${ss.length}종목</span>${clSet.has(g)?` <span class="badge up">군집</span>`:""}</div><div class="nhgrid">`;
    for(const st of ss){
      const mat = nhMat(st.filings, "f") + nhMat(st.news, "n");
      h += `<div class="nhcard"><div class="nhh"><div><b>${esc(st.name)}</b> <small class="mono">${esc(st.code)}</small></div>
          <div class="mono"><span class="pos"><b>${fmt(st.change)}%</b></span> <span class="badge${st.kind==="ATH"?" up":""}">${KIND[st.kind]}</span></div></div>
        <div class="nhm">${esc(st.industry||"")} · 시총 ${moneyFmt(st.mcap, cur)}${st.rank?` · 상승률 ${st.rank}위`:""}</div>
        ${nhChart(st.chart)}
        <div class="nhl">${nhLinks(st)}</div>
        ${mat ? `<ul class="nhmat">${mat}</ul>` : `<div class="nhmat-none">최근 공시·뉴스 없음</div>`}</div>`;
    }
    h += `</div></div>`;
  }
  if(!stocks.length) h += `<div class="card"><div class="empty-state">조건에 맞는 종목이 없음.</div></div>`;

  // 신고가 이후 성과
  const fl = (D.follow||[]).slice().sort((a,b) => (a.ret-b.ret)*followSort);
  if(fl.length){
    h += `<h2 class="sh">신고가 이후 성과 <span class="tag">최근 ${new Set(fl.map(x=>x.date)).size} 기록일 · 기록 당일 종가 → 최신 종가</span></h2>
      <p class="sdesc">지난 기록일에 신고가로 잡힌 종목이 지금까지 얼마나 이어졌는지. 라벨별 중앙값은 위 군집 표 '신고가 이후' 칸에 있음. 표본이 작고 기간이 짧아 참고용임.</p>
      <div class="card"><div class="scroll" style="max-height:520px;overflow:auto"><table class="tbl"><thead><tr><th class="l">신고가일</th><th class="l">종목</th><th class="l">라벨</th><th>구분</th><th class="sortable sorted" data-fs="1">이후 수익률 ${followSort<0?"▾":"▴"}</th><th>경과 거래일</th></tr></thead><tbody>` +
      fl.slice(0, 200).map(x => `<tr><td class="l mono">${esc(x.date)}</td><td class="l"><b>${esc(x.name)}</b> <small class="mono" style="color:var(--ink3)">${esc(x.code)}</small></td><td class="l">${esc(x.label)}</td><td class="ctr">${KIND[x.kind]||esc(x.kind)}</td><td class="mono ${x.ret>=0?"pos":"neg"}" style="${heat(x.ret, 15)}">${fmt(x.ret)}%</td><td class="mono">${x.days}</td></tr>`).join("") +
      `</tbody></table></div></div>`;
  }
  $("#view").innerHTML = h;
  $("#nhday").onchange = e => { NHDAY = e.target.value; render(); };
  $("#nhlab").onchange = e => { nhF.label = e.target.value; render(); };
}

init();
