/* 문의 등록 페이지 동작 — 백엔드 POST /inquiries 호출 */
(function () {
  var textarea = document.getElementById("question");
  var btn = document.getElementById("submit-btn");
  var toast = document.getElementById("toast");
  var toastTimer = null;

  function showToast(message, isError) {
    toast.textContent = message;
    toast.classList.toggle("error", !!isError);
    toast.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove("show");
    }, 3500);
  }

  btn.addEventListener("click", function () {
    var value = textarea.value.trim();
    if (!value) {
      textarea.focus();
      return;
    }

    btn.disabled = true;
    var original = btn.textContent;
    btn.textContent = "등록 중...";

    log("문의 등록 시도");
    postInquiry(value)
      .then(function () {
        textarea.value = "";
        log("문의 등록 성공");
        showToast("문의가 등록되었습니다.");
      })
      .catch(function (err) {
        logError("문의 등록 실패:", err.message);
        showToast("등록에 실패했습니다. 서버 상태를 확인해주세요. (" + err.message + ")", true);
      })
      .then(function () {
        btn.disabled = false;
        btn.textContent = original;
      });
  });
})();
