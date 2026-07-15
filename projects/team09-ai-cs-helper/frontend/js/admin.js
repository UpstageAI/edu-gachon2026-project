/* 관리자 페이지 — 백엔드 API 연동 */
(function () {
  "use strict";

  var DONE_STATUS = "답변 완료";       // 이 상태면 처리 완료로 간주 (그 외는 처리대기)

  var inquiries = [];                  // API 또는 mock에서 채움
  var offline = false;

  var viewState = {
    all: { selectedId: null, category: "전체", status: "전체", sort: "newest" },
    pending: { selectedId: null, category: "전체", status: "전체", sort: "newest" },
  };

  // ---------- 유틸 ----------
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }
  function reviewerLabel(r) {
    if (!r) return "-";
    return String(r).toLowerCase() === "ai" ? "AI" : "상담원";
  }
  function reviewerClass(r) {
    return String(r).toLowerCase() === "ai" ? "AI" : (r ? "human" : "none");
  }
  function pct(value, total) {
    return total ? Math.round((value / total) * 100) : 0;
  }
  function fmtDate(s) {
    if (!s) return "";
    return String(s).replace("T", " ").slice(0, 16);   // YYYY-MM-DD HH:MM
  }
  function normalizeDocs(docs) {
    if (!Array.isArray(docs)) return [];
    return docs.map(function (d) {
      if (typeof d === "string") return d;
      if (d && d.content) return d.content;
      return JSON.stringify(d);
    });
  }
  // DB 행을 UI가 기대하는 형태로 정규화
  function normalize(row) {
    return {
      inquiry_id: row.inquiry_id,
      created_at: row.created_at,
      question: row.question || "",
      categories: row.categories || "미분류",
      status: row.status || "접수",
      reviewer_type: row.reviewer_type || null,
      retrieved_docs: normalizeDocs(row.retrieved_docs),
      ai_answer: row.ai_answer || null,
      final_answer: row.final_answer || null,
    };
  }

  function distinct(values) {
    var seen = [];
    values.forEach(function (v) {
      if (v != null && v !== "" && seen.indexOf(v) < 0) seen.push(v);
    });
    return seen;
  }
  function allCategories() { return distinct(inquiries.map(function (i) { return i.categories; })); }
  function allStatuses() { return distinct(inquiries.map(function (i) { return i.status; })); }

  function isPending(i) { return i.status !== DONE_STATUS; }

  function baseData(view) {
    return view === "pending" ? inquiries.filter(isPending) : inquiries.slice();
  }

  function visibleData(view) {
    var s = viewState[view];
    var rows = baseData(view).filter(function (i) {
      if (s.category !== "전체" && i.categories !== s.category) return false;
      if (s.status !== "전체" && i.status !== s.status) return false;
      return true;
    });
    rows.sort(function (a, b) {
      if (view === "pending") {              // 처리대기: 긴급 카테고리 최상단
        var ua = a.categories === "긴급" ? 0 : 1;
        var ub = b.categories === "긴급" ? 0 : 1;
        if (ua !== ub) return ua - ub;
      }
      var cmp = a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0;
      return s.sort === "oldest" ? cmp : -cmp;
    });
    return rows;
  }

  function findById(id) {
    for (var i = 0; i < inquiries.length; i++) {
      if (inquiries[i].inquiry_id === id) return inquiries[i];
    }
    return null;
  }

  // ---------- 툴바 ----------
  function optionList(values, current) {
    return values.map(function (v) {
      return '<option value="' + esc(v) + '"' + (v === current ? " selected" : "") + ">" + esc(v) + "</option>";
    }).join("");
  }
  function buildToolbar(view) {
    var s = viewState[view];
    var statusValues = view === "pending"
      ? allStatuses().filter(isPendingStatus)
      : allStatuses();
    var toolbar = document.getElementById("toolbar-" + view);
    toolbar.innerHTML =
      '<div class="field"><label>카테고리</label>' +
        '<select data-role="category"><option value="전체"' +
        (s.category === "전체" ? " selected" : "") + ">전체</option>" +
        optionList(allCategories(), s.category) + "</select></div>" +
      '<div class="field"><label>상태</label>' +
        '<select data-role="status"><option value="전체"' +
        (s.status === "전체" ? " selected" : "") + ">전체</option>" +
        optionList(statusValues, s.status) + "</select></div>" +
      '<div class="field"><label>정렬</label>' +
        '<select data-role="sort">' +
        '<option value="newest"' + (s.sort === "newest" ? " selected" : "") + ">최신순</option>" +
        '<option value="oldest"' + (s.sort === "oldest" ? " selected" : "") + ">오래된순</option>" +
        "</select></div>";
    // onchange 할당(재빌드해도 리스너가 중복되지 않음)
    toolbar.onchange = function (e) {
      var role = e.target.getAttribute("data-role");
      if (!role) return;
      viewState[view][role] = e.target.value;
      renderList(view);
    };
  }
  function isPendingStatus(s) { return s !== DONE_STATUS; }

  // ---------- 리스트 ----------
  function renderList(view) {
    var container = document.getElementById("list-" + view);
    var rows = visibleData(view);
    container.innerHTML = "";
    if (!rows.length) {
      container.appendChild(el('<div class="list-empty">조건에 맞는 문의가 없습니다.</div>'));
      return;
    }
    rows.forEach(function (item) {
      var node = el(
        '<div class="item" tabindex="0">' +
          '<div class="item-top">' +
            '<span class="badge cat-' + esc(item.categories) + '">' + esc(item.categories) + "</span>" +
            '<span class="item-date">' + esc(fmtDate(item.created_at)) + "</span>" +
          "</div>" +
          '<div class="item-q">' + esc(item.question) + "</div>" +
          '<div class="item-badges">' +
            '<span class="badge st-' + esc(item.status) + '">' + esc(item.status) + "</span>" +
            '<span class="badge reviewer-' + esc(reviewerClass(item.reviewer_type)) + '">' +
              esc(reviewerLabel(item.reviewer_type)) + "</span>" +
          "</div>" +
        "</div>"
      );
      if (viewState[view].selectedId === item.inquiry_id) node.classList.add("selected");
      node.addEventListener("click", function () {
        viewState[view].selectedId = item.inquiry_id;
        renderList(view);
        renderDetail(view);
      });
      container.appendChild(node);
    });
  }

  // ---------- 상세 ----------
  function renderDetail(view) {
    var container = document.getElementById("detail-" + view);
    var id = viewState[view].selectedId;
    var item = id ? findById(id) : null;
    if (!item) {
      container.innerHTML = '<div class="detail-empty">왼쪽 목록에서 문의를 선택하세요.</div>';
      return;
    }

    var docsHtml = item.retrieved_docs.length
      ? '<ul class="docs">' + item.retrieved_docs.map(function (d) {
          return "<li>" + esc(d) + "</li>";
        }).join("") + "</ul>"
      : '<div class="docs-empty">검색된 참고 문서가 없습니다.</div>';

    container.innerHTML =
      '<div class="detail-heading"><h3>문의 상세</h3>' +
        '<button type="button" class="btn danger" data-role="delete-inquiry">상담내역 삭제</button></div>' +
      '<dl class="meta-grid">' +
        "<dt>등록일시</dt><dd>" + esc(fmtDate(item.created_at)) + "</dd>" +
        "<dt>카테고리</dt><dd><span class='badge cat-" + esc(item.categories) + "'>" + esc(item.categories) + "</span></dd>" +
        "<dt>상태</dt><dd><span class='badge st-" + esc(item.status) + "'>" + esc(item.status) + "</span></dd>" +
        "<dt>답변자</dt><dd>" + esc(reviewerLabel(item.reviewer_type)) + "</dd>" +
      "</dl>" +
      '<div class="section-label">문의 내용</div>' +
      '<div class="question-box">' + esc(item.question) + "</div>" +
      '<div class="section-label">참고 문서 (RAG)</div>' + docsHtml +
      '<div class="section-label">답변</div>' +
      '<div id="answer-slot"></div>' +
      '<div class="section-label">AI 처리 과정</div>' +
      '<div class="timeline" data-role="processing-timeline">' +
        '<div class="timeline-empty">처리 로그를 불러오는 중...</div>' +
      "</div>";

    container.querySelector('[data-role="delete-inquiry"]').addEventListener("click", function () {
      requestDelete(view, item, this);
    });

    renderAnswer(container.querySelector("#answer-slot"), view, item);
    loadTimeline(container.querySelector('[data-role="processing-timeline"]'), item);
  }

  function timelineClass(entry) {
    if (entry.event.indexOf("failed") >= 0) return "error";
    if (entry.event.indexOf("retry") >= 0 || entry.event.indexOf("regenerated") >= 0) return "warning";
    if (entry.stage === "database") return "database";
    if (entry.stage === "human") return "human";
    if (entry.event.indexOf("passed") >= 0 || entry.event === "completed") return "success";
    return "info";
  }

  function timelineMeta(entry) {
    var parts = [];
    if (entry.attempt != null) parts.push(entry.attempt + "차");
    if (entry.duration_ms != null) parts.push(entry.duration_ms + "ms");
    var tokenUsage = entry.data && entry.data.token_usage;
    if (tokenUsage && tokenUsage.total_tokens != null) {
      parts.push("총 " + tokenUsage.total_tokens.toLocaleString("ko-KR") + "토큰");
    }
    parts.push(fmtDate(entry.created_at));
    return parts.filter(Boolean).join(" · ");
  }

  function renderTimeline(slot, entries) {
    if (!entries.length) {
      slot.innerHTML = '<div class="timeline-empty">저장된 처리 로그가 없습니다.</div>';
      return;
    }
    slot.innerHTML = entries.map(function (entry) {
      var hasData = entry.data && Object.keys(entry.data).length;
      var detail = hasData
        ? '<details class="timeline-detail"><summary>상세 데이터 보기</summary>' +
          '<pre>' + esc(JSON.stringify(entry.data, null, 2)) + "</pre></details>"
        : "";
      return '<article class="timeline-item ' + timelineClass(entry) + '">' +
        '<span class="timeline-dot" aria-hidden="true"></span>' +
        '<div class="timeline-body">' +
          '<div class="timeline-head"><strong>' + esc(entry.title) + "</strong>" +
            '<span>' + esc(timelineMeta(entry)) + "</span></div>" +
          (entry.message ? '<p>' + esc(entry.message) + "</p>" : "") +
          detail +
        "</div></article>";
    }).join("");
  }

  function loadTimeline(slot, item) {
    if (offline) {
      slot.innerHTML = '<div class="timeline-empty">오프라인 데모에서는 처리 로그를 조회하지 않습니다.</div>';
      return;
    }
    getInquiryLogs(item.inquiry_id)
      .then(function (entries) { renderTimeline(slot, entries); })
      .catch(function (err) {
        slot.innerHTML = '<div class="timeline-empty error-text">로그 조회 실패: ' + esc(err.message) + "</div>";
      });
  }

  function recordUiAction(item, event) {
    if (offline) return;
    postLogAction(item.inquiry_id, event).catch(function () {
      // 행동 로그 실패는 답변 수정 UI를 막지 않는다.
    });
  }

  function removeFromScreen(inquiryId) {
    inquiries = inquiries.filter(function (item) { return item.inquiry_id !== inquiryId; });
    if (viewState.all.selectedId === inquiryId) viewState.all.selectedId = null;
    if (viewState.pending.selectedId === inquiryId) viewState.pending.selectedId = null;
    renderEverything();
  }

  function requestDelete(view, item, btn) {
    if (!window.confirm("이 상담 내역을 삭제하시겠습니까? 삭제 후 복구할 수 없습니다.")) return;

    if (offline) {
      log("삭제(오프라인): inquiry_id=" + item.inquiry_id + " — DB 미반영");
      removeFromScreen(item.inquiry_id);
      return;
    }

    btn.disabled = true;
    btn.textContent = "삭제 중...";
    deleteInquiry(item.inquiry_id)
      .then(function () { removeFromScreen(item.inquiry_id); })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "상담내역 삭제";
        window.alert("삭제에 실패했습니다. (" + err.message + ")");
      });
  }

  function renderAnswer(slot, view, item) {
    if (item.final_answer) {
      slot.innerHTML =
        '<p class="answer-note">✓ 최종 답변이 등록되었습니다.</p>' +
        '<div class="answer-final">' + esc(item.final_answer) + "</div>";
      return;
    }
    var hasAiAnswer = !!String(item.ai_answer || "").trim();
    var noteHtml = hasAiAnswer
      ? '<p class="answer-note">AI 답변을 승인하거나 수정할 수 있습니다.</p>'
      : '<p class="answer-note">AI 답변 없음 — 상담원이 직접 작성해야 합니다.</p>';
    var buttonsHtml = hasAiAnswer
      ? '<button type="button" class="btn" id="approve-answer">답변 승인</button>' +
        '<button type="button" class="btn secondary" id="edit-answer">수정</button>'
      : '<button type="button" class="btn" id="register-answer">답변 등록</button>';
    slot.innerHTML =
      noteHtml +
      '<textarea id="answer-input" placeholder="답변을 입력하세요"' +
        (hasAiAnswer ? " readonly" : "") + ">" + esc(item.ai_answer || "") + "</textarea>" +
      '<div class="answer-actions">' +
        buttonsHtml +
        '<span class="answer-note" id="save-msg"></span>' +
      "</div>";

    var approveBtn = slot.querySelector("#approve-answer");
    if (approveBtn) {
      approveBtn.addEventListener("click", function () {
        saveAnswer(view, item, String(item.ai_answer).trim(), approveBtn, slot.querySelector("#save-msg"));
      });
    }

    var editBtn = slot.querySelector("#edit-answer");
    if (editBtn) {
      editBtn.addEventListener("click", function () {
        enterAnswerEditMode(slot, view, item);
      });
    }

    var registerBtn = slot.querySelector("#register-answer");
    if (registerBtn) registerBtn.addEventListener("click", function () {
      var input = slot.querySelector("#answer-input");
      var value = input.value.trim();
      if (!value) { input.focus(); return; }
      saveAnswer(view, item, value, this, slot.querySelector("#save-msg"));
    });
  }

  function enterAnswerEditMode(slot, view, item) {
    var input = slot.querySelector("#answer-input");
    var actions = slot.querySelector(".answer-actions");
    recordUiAction(item, "edit_started");
    input.readOnly = false;
    actions.innerHTML =
      '<button type="button" class="btn" id="register-answer">답변 등록</button>' +
      '<button type="button" class="btn secondary" id="cancel-edit">수정 취소</button>' +
      '<span class="answer-note" id="save-msg"></span>';

    actions.querySelector("#register-answer").addEventListener("click", function () {
      var value = input.value.trim();
      if (!value) { input.focus(); return; }
      saveAnswer(view, item, value, this, actions.querySelector("#save-msg"));
    });
    actions.querySelector("#cancel-edit").addEventListener("click", function () {
      recordUiAction(item, "edit_cancelled");
      renderAnswer(slot, view, item);
    });
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  function applySaved(item, value, updated) {
    item.final_answer = (updated && updated.final_answer) || value;
    item.status = (updated && updated.status) || DONE_STATUS;
    var aiAnswer = String(item.ai_answer || "").trim();
    var inferredReviewer = aiAnswer && value.trim() === aiAnswer ? "ai" : "human";
    item.reviewer_type = (updated && updated.reviewer_type) || inferredReviewer;
  }
  function afterSave(view) {
    renderDetail(view);
    renderList("all");
    renderList("pending");
    document.getElementById("pending-count").textContent = baseData("pending").length;
  }

  function saveAnswer(view, item, value, btn, msg) {
    if (offline) {
      log("저장(오프라인): inquiry_id=" + item.inquiry_id + " — DB 미반영");
      applySaved(item, value, null);
      afterSave(view);
      return;
    }
    log("저장 요청: inquiry_id=" + item.inquiry_id);
    btn.disabled = true;
    msg.textContent = "저장 중...";
    patchAnswer(item.inquiry_id, value)
      .then(function (updated) {
        applySaved(item, value, updated);
        afterSave(view);
      })
      .catch(function (err) {
        btn.disabled = false;
        msg.textContent = "저장 실패: " + err.message;
      });
  }

  // ---------- 통계 ----------
  function barsHtml(title, entries, total, colors) {
    var rows = entries.map(function (e, idx) {
      var color = colors ? colors[idx % colors.length] : "var(--accent)";
      var width = total ? (e.value / total) * 100 : 0;
      return (
        '<div class="bar-row">' +
          '<span class="bar-name">' + esc(e.name) + "</span>" +
          '<span class="bar-track"><span class="bar-fill" style="width:' +
            width.toFixed(1) + "%;background:" + color + '"></span></span>' +
          '<span class="bar-val">' + e.value + '<small> · ' + pct(e.value, total) + "%</small></span>" +
        "</div>"
      );
    }).join("");
    return '<div class="card chart"><h4>' + esc(title) + '</h4><div class="bars">' + rows + "</div></div>";
  }

  function countMap(keyFn) {
    var map = {};
    inquiries.forEach(function (i) {
      var k = keyFn(i);
      map[k] = (map[k] || 0) + 1;
    });
    return map;
  }

  function heatmapHtml(title, rowKeys, colKeys) {
    var counts = {}, max = 0;
    rowKeys.forEach(function (r) { counts[r] = {}; colKeys.forEach(function (c) { counts[r][c] = 0; }); });
    inquiries.forEach(function (i) {
      if (counts[i.categories] && counts[i.categories][i.status] !== undefined) {
        var v = ++counts[i.categories][i.status];
        if (v > max) max = v;
      }
    });
    var head = "<tr><th></th>" + colKeys.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") + "</tr>";
    var body = rowKeys.map(function (r) {
      var cells = colKeys.map(function (c) {
        var v = counts[r][c];
        var ratio = max ? v / max : 0;
        var alpha = v ? (0.10 + ratio * 0.55).toFixed(2) : 0;
        var bg = v ? "rgba(42,120,214," + alpha + ")" : "var(--surface-1)";
        return '<td class="cell" style="background:' + bg + '">' + (v || "") + "</td>";
      }).join("");
      return '<tr><td class="rowhead">' + esc(r) + "</td>" + cells + "</tr>";
    }).join("");
    return (
      '<div class="card chart"><h4>' + esc(title) + "</h4>" +
      '<div class="heatmap"><table><thead>' + head + "</thead><tbody>" + body + "</tbody></table></div></div>"
    );
  }

  function renderStats() {
    var total = inquiries.length;
    var aiCount = inquiries.filter(function (i) { return String(i.reviewer_type).toLowerCase() === "ai"; }).length;
    var humanCount = inquiries.filter(function (i) { return String(i.reviewer_type).toLowerCase() === "human"; }).length;
    var pendingCount = baseData("pending").length;

    document.getElementById("kpi-row").innerHTML =
      '<div class="card kpi"><div class="kpi-label">전체 문의</div>' +
        '<div class="kpi-value">' + total + ' <small>건</small></div>' +
        '<div class="kpi-sub">누적 접수 기준</div></div>' +
      '<div class="card kpi"><div class="kpi-label">AI 자동응답률</div>' +
        '<div class="kpi-value">' + pct(aiCount, total) + '<small>%</small></div>' +
        '<div class="kpi-sub">' + aiCount + ' / ' + total + '건</div></div>' +
      '<div class="card kpi"><div class="kpi-label">처리대기</div>' +
        '<div class="kpi-value">' + pendingCount + ' <small>건</small></div>' +
        '<div class="kpi-sub">전체의 ' + pct(pendingCount, total) + '%</div></div>';

    var catMap = countMap(function (i) { return i.categories; });
    var stMap = countMap(function (i) { return i.status; });
    var cats = allCategories();
    var sts = allStatuses();

    var catEntries = cats.map(function (c) { return { name: c, value: catMap[c] || 0 }; });
    var stEntries = sts.map(function (s) { return { name: s, value: stMap[s] || 0 }; });
    var revEntries = [
      { name: "AI", value: aiCount },
      { name: "상담원", value: humanCount },
    ];
    var catColors = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
    var revColors = ["var(--series-1)", "var(--series-2)"];

    document.getElementById("charts-grid").innerHTML =
      barsHtml("카테고리별", catEntries, total, catColors) +
      barsHtml("상태별", stEntries, total, null) +
      barsHtml("답변자별", revEntries, total, revColors) +
      heatmapHtml("카테고리 × 상태", cats, sts);
  }

  // ---------- 탭 ----------
  function switchTab(tab) {
    document.querySelectorAll(".tab").forEach(function (t) {
      t.classList.toggle("active", t.getAttribute("data-tab") === tab);
    });
    document.querySelectorAll(".panel").forEach(function (p) {
      p.classList.toggle("active", p.id === "panel-" + tab);
    });
    if (tab === "stats") renderStats();
  }
  document.getElementById("tabs").addEventListener("click", function (e) {
    var btn = e.target.closest(".tab");
    if (btn) switchTab(btn.getAttribute("data-tab"));
  });

  // ---------- 렌더 전체 ----------
  function renderEverything() {
    document.getElementById("pending-count").textContent = baseData("pending").length;
    buildToolbar("all");
    buildToolbar("pending");
    renderList("all");
    renderDetail("all");
    renderList("pending");
    renderDetail("pending");
  }

  function showOfflineBanner() {
    var main = document.querySelector("main.container");
    if (!main || document.getElementById("offline-banner")) return;
    var banner = el('<div class="offline-banner" id="offline-banner">⚠ 백엔드에 연결하지 못했습니다. 서버 상태를 확인한 뒤 페이지를 새로고침해 주세요.</div>');
    main.insertBefore(banner, main.firstChild);
  }

  // ---------- 부팅: 백엔드 API 조회 ----------
  function boot() {
    getInquiries()
      .then(function (rows) {
        inquiries = rows.map(normalize);
        offline = false;
        log("관리자 부팅: API 연결 성공,", inquiries.length, "건 로드");
        renderEverything();
      })
      .catch(function () {
        inquiries = [];
        offline = true;
        logError("관리자 부팅: API 연결 실패");
        showOfflineBanner();
        renderEverything();
      });
  }

  boot();
})();
