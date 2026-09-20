"use strict";
let accessToken = "";
const el = (id) => document.getElementById(id);
const status = (message, bad = false) => {
  el("status").textContent = message;
  el("status").className = bad ? "error" : "muted";
};
const node = (tag, className, content) => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content !== undefined) item.textContent = content;
  return item;
};
async function api(path, data) {
  const init = {headers: {"X-Console-Token": accessToken}};
  if (data !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(data);
  }
  const response = await fetch(path, init);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || ("HTTP " + response.status));
  return payload;
}
async function loadSources() {
  const {sources} = await api("/api/sources");
  const root = el("sources");
  root.replaceChildren();
  if (!sources.length) root.append(node("p", "muted", "まだ収集元は登録されていません。"));
  for (const source of sources) {
    const entry = node("div", "source");
    const name = node("div", "", (source.kind === "user" ? "@" : "検索：") + source.value);
    const controls = node("div", "horizontal");
    const run = node("button", "secondary", "調査する");
    run.onclick = async () => {
      run.disabled = true;
      status("調査中：" + source.value);
      try {
        const result = await api("/api/research", {source_id: source.id, limit: 10});
        status("取得 " + result.fetched + "件・新規 " + result.new + "件（" + result.backend + "）。" +
          (result.warnings || []).join(" "));
        await loadFindings();
      } catch (error) { status("調査失敗：" + error.message, true); }
      finally { run.disabled = false; }
    };
    const remove = node("button", "danger", "削除");
    remove.onclick = async () => {
      if (!confirm("この収集元を削除しますか？取得済みの投稿は残ります。")) return;
      try { await api("/api/sources/delete", {source_id: source.id}); await loadSources(); }
      catch (error) { status(error.message, true); }
    };
    controls.append(run, remove);
    entry.append(name, controls);
    root.append(entry);
  }
}
async function loadFindings() {
  const {findings} = await api("/api/findings");
  el("count").textContent = "保存済み " + findings.length + "件（最大300件表示）";
  const root = el("findings");
  root.replaceChildren();
  if (!findings.length) root.append(node("p", "muted", "調査を実行すると投稿が表示されます。"));
  for (const finding of findings) {
    const card = node("article", "finding");
    const title = node("div", "horizontal");
    const author = node("strong", "", "@" + (finding.author || "unknown"));
    const date = node("span", "muted", finding.published_at || "日時不明");
    title.append(author, date);
    const body = node("p", "content", finding.content);
    const link = node("a", "", "Xで元投稿を確認 ↗");
    const url = finding.url;
    if (url && /^https:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/[A-Za-z0-9_]+\/status\/\d+$/.test(url)) {
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    } else {
      link.textContent = "投稿ID：" + finding.post_id;
    }
    const category = node("select", "");
    for (const [value, label] of [["other","未分類"],["event","イベント・配信"],["product","商品"],["deadline","締切"]]) {
      const opt = node("option", "", label); opt.value = value;
      category.append(opt);
    }
    category.value = finding.category;
    const review = node("select", "");
    for (const [value, label] of [["new","要確認"],["reviewed","確認済み"],["ignored","対象外"]]) {
      const opt = node("option", "", label); opt.value = value;
      review.append(opt);
    }
    review.value = finding.state;
    const notes = node("textarea", ""); notes.value = finding.notes || "";
    notes.maxLength = 2000; notes.rows = 2; notes.placeholder = "登録候補の日時・URL・確認事項";
    const save = node("button", "secondary", "レビューを保存");
    save.onclick = async () => {
      save.disabled = true;
      try {
        await api("/api/findings/review", {post_id: finding.post_id, category: category.value,
          state: review.value, notes: notes.value});
        status("レビューを保存しました：" + finding.post_id);
      } catch (error) { status(error.message, true); }
      finally { save.disabled = false; }
    };
    const reviewRow = node("div", "horizontal");
    reviewRow.append(category, review, save);
    const origin = node("p", "muted", "取得元：" + (finding.source_backend || "不明") + " / 投稿ID：" + finding.post_id);
    card.append(title, body, link, origin, reviewRow, notes);
    root.append(card);
  }
}
el("connect").onclick = async () => {
  const entered = el("token").value;
  if (!entered) return status("アクセスキーを入力してください。", true);
  accessToken = entered;
  el("token").value = "";
  try { await Promise.all([loadSources(), loadFindings()]); status("接続しました。読み取り専用モードです。"); }
  catch (error) { accessToken = ""; status("接続失敗：" + error.message, true); }
};
el("source-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("/api/sources", {kind: el("kind").value, value: el("value").value});
    el("value").value = "";
    await loadSources();
    status("収集元を登録しました。");
  } catch (error) { status(error.message, true); }
};
el("reload").onclick = async () => {
  try { await loadFindings(); status("更新しました。"); }
  catch (error) { status(error.message, true); }
};
