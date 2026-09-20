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
    const name = node("div", "", (source.label ? source.label + " · " : "") + (source.kind === "user" ? "@" : source.kind === "query" ? "X検索：" : "Web：") + source.value);
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
        await loadCollections();
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
async function loadCollections() {
  const {collections} = await api("/api/collections");
  const select = el("filter-collection");
  const current = select.value;
  select.replaceChildren();
  const all = node("option", "", "すべて");
  all.value = "";
  select.append(all);
  for (const name of collections) {
    const option = node("option", "", name);
    option.value = name;
    select.append(option);
  }
  select.value = collections.includes(current) ? current : "";
}

async function loadFindings() {
  const params = new URLSearchParams({
    state: el("filter-state").value,
    collection: el("filter-collection").value,
    q: el("filter-query").value.trim(),
  });
  const {items} = await api("/api/items?" + params.toString());
  el("count").textContent = "表示 " + items.length + "件（最大300件）";
  const root = el("findings");
  root.replaceChildren();
  if (!items.length) root.append(node("p", "muted", "一致するデータがありません。収集元を登録して調査するか、フィルターを変更してください。"));
  for (const item of items) {
    const card = node("article", "finding");
    const title = node("div", "horizontal");
    const author = node("strong", "", (item.platform === "x" ? "@" : "") + (item.author || item.title || item.url || "unknown"));
    const date = node("span", "muted", item.published_at || item.captured_at || "日時不明");
    title.append(author, date);
    const body = node("p", "content", item.content);
    const link = node("a", "", "元の情報を開く ↗");
    try {
      const url = new URL(item.url);
      if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) {
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      } else { link.textContent = "参照ID：" + item.external_id; }
    } catch { link.textContent = "参照ID：" + item.external_id; }
    const review = node("select", "");
    for (const [value, label] of [["new","要確認"],["reviewed","確認済み"],["ignored","対象外"]]) {
      const option = node("option", "", label); option.value = value;
      review.append(option);
    }
    review.value = item.state;
    const tagsLabel = node("label", "", "タグ（カンマ区切り）");
    const tags = node("input", ""); tags.value = item.tags.join(", ");
    tags.maxLength = 500; tags.placeholder = "例：イベント, 締切, 調査資料";
    const collectionsLabel = node("label", "", "コレクション（カンマ区切り）");
    const collections = node("input", ""); collections.value = item.collections.join(", ");
    collections.maxLength = 500; collections.placeholder = "例：ラブライブ, 案件調査";
    const notesLabel = node("label", "", "メモ");
    const notes = node("textarea", ""); notes.value = item.notes || "";
    notes.maxLength = 2000; notes.rows = 2; notes.placeholder = "確認内容・次の作業";
    const save = node("button", "secondary", "整理内容を保存");
    save.onclick = async () => {
      save.disabled = true;
      try {
        await api("/api/items/review", {
          item_id: item.item_id, state: review.value, notes: notes.value,
          tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
          collections: collections.value.split(",").map((t) => t.trim()).filter(Boolean),
        });
        status("保存しました：" + item.item_id);
        await loadCollections();
      } catch (error) { status("保存失敗：" + error.message, true); }
      finally { save.disabled = false; }
    };
    const reviewRow = node("div", "horizontal");
    reviewRow.append(review, save);
    const origin = node("p", "muted", "プラットフォーム：" + item.platform + " / バックエンド：" +
      (item.backend || "不明") + " / ID：" + item.external_id);
    card.append(title, body, link, origin, reviewRow, tagsLabel, tags,
      collectionsLabel, collections, notesLabel, notes);
    root.append(card);
  }
}
el("connect").onclick = async () => {
  const entered = el("token").value;
  if (!entered) return status("アクセスキーを入力してください。", true);
  accessToken = entered;
  el("token").value = "";
  try { await loadCollections(); await Promise.all([loadSources(), loadFindings()]); status("接続しました。収集・整理モードです。"); }
  catch (error) { accessToken = ""; status("接続失敗：" + error.message, true); }
};
el("source-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("/api/sources", {kind: el("kind").value, value: el("value").value,
      label: el("source-label").value});
    el("value").value = "";
    el("source-label").value = "";
    await loadSources();
    status("収集元を登録しました。");
  } catch (error) { status(error.message, true); }
};
el("reload").onclick = async () => {
  try { await loadFindings(); status("更新しました。"); }
  catch (error) { status(error.message, true); }
};

for (const name of ["filter-state", "filter-collection"]) {
  el(name).addEventListener("change", () => { if (accessToken) loadFindings().catch(e => status(e.message, true)); });
}
el("filter-query").addEventListener("change", () => {
  if (accessToken) loadFindings().catch(e => status(e.message, true));
});
el("kind").addEventListener("change", () => {
  el("value").placeholder = el("kind").value === "web" ? "https://example.com/news" :
    el("kind").value === "user" ? "LoveLive_staff" : "検索キーワード";
});
