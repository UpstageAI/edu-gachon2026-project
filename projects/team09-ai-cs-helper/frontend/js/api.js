/*
 * 백엔드 API 호출 래퍼.
 * 배포된 GCP 백엔드 API를 사용한다.
 * (배포 위치가 바뀌면 API_BASE만 수정하면 된다.)
 */

var API_BASE = "http://34.50.51.111:8000";

// 전체 문의 목록 (최신순)
function getInquiries() {
  log("GET", API_BASE + "/inquiries");
  return fetch(API_BASE + "/inquiries").then(function (res) {
    if (!res.ok) throw new Error("GET /inquiries " + res.status);
    return res.json();
  }).then(function (data) {
    log("GET /inquiries ->", data.length, "건");
    return data;
  }).catch(function (err) {
    logError("GET /inquiries 실패:", err.message);
    throw err;
  });
}

// 문의별 처리 로그 (sequence 오름차순)
function getInquiryLogs(inquiryId) {
  var path = "/inquiries/" + encodeURIComponent(inquiryId) + "/logs";
  log("GET " + path);
  return fetch(API_BASE + path)
    .then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        if (!res.ok) {
          var detail = body && body.detail ? " · " + body.detail : "";
          throw new Error("GET " + path + " " + res.status + detail);
        }
        return body;
      });
    }).catch(function (err) {
      logError("문의 처리 로그 조회 실패:", err.message);
      throw err;
    });
}

// 수정 시작/취소처럼 DB 변경이 없는 상담원 행동 기록
function postLogAction(inquiryId, event) {
  return fetch(API_BASE + "/inquiries/" + encodeURIComponent(inquiryId) + "/logs/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event: event }),
  }).then(function (res) {
    if (!res.ok) throw new Error("POST /inquiries/{id}/logs/actions " + res.status);
    return res.json();
  }).catch(function (err) {
    logError("상담원 행동 로그 저장 실패:", err.message);
    throw err;
  });
}

// 최종 답변 저장 (관리자 승인/작성)
function patchAnswer(inquiryId, finalAnswer) {
  log("PATCH /inquiries/" + inquiryId);
  return fetch(API_BASE + "/inquiries/" + encodeURIComponent(inquiryId), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ final_answer: finalAnswer }),
  }).then(function (res) {
    if (!res.ok) throw new Error("PATCH /inquiries " + res.status);
    return res.json();
  }).then(function (data) {
    log("PATCH /inquiries/" + inquiryId + " -> 저장 완료");
    return data;
  }).catch(function (err) {
    logError("PATCH /inquiries 실패:", err.message);
    throw err;
  });
}

// 상담 내역 영구 삭제
function deleteInquiry(inquiryId) {
  log("DELETE /inquiries/" + inquiryId);
  return fetch(API_BASE + "/inquiries/" + encodeURIComponent(inquiryId), {
    method: "DELETE",
  }).then(function (res) {
    if (!res.ok) throw new Error("DELETE /inquiries " + res.status);
    return res.json();
  }).then(function (data) {
    log("DELETE /inquiries/" + inquiryId + " -> 삭제 완료");
    return data;
  }).catch(function (err) {
    logError("DELETE /inquiries 실패:", err.message);
    throw err;
  });
}

// 문의 등록 (그래프 파이프라인 실행)
function postInquiry(text) {
  log("POST /inquiries (" + text.length + "자)");
  return fetch(API_BASE + "/inquiries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text }),
  }).then(function (res) {
    if (!res.ok) throw new Error("POST /inquiries " + res.status);
    return res.json();
  }).then(function (data) {
    log("POST /inquiries -> inquiry_id=" + data.inquiry_id);
    return data;
  }).catch(function (err) {
    logError("POST /inquiries 실패:", err.message);
    throw err;
  });
}

window.API_BASE = API_BASE;
window.getInquiries = getInquiries;
window.patchAnswer = patchAnswer;
window.postInquiry = postInquiry;
window.deleteInquiry = deleteInquiry;
window.getInquiryLogs = getInquiryLogs;
window.postLogAction = postLogAction;
