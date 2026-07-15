/*
 * 프론트엔드 로깅 헬퍼 (데모 디버깅용).
 * DEBUG=false 로 두면 일반 로그는 조용해지고, 에러만 남는다.
 */

var DEBUG = true;

function log() {
  if (!DEBUG) return;
  var args = Array.prototype.slice.call(arguments);
  console.log.apply(console, ["[cs]"].concat(args));
}

function logError() {
  var args = Array.prototype.slice.call(arguments);
  console.error.apply(console, ["[cs]"].concat(args));
}

window.DEBUG = DEBUG;
window.log = log;
window.logError = logError;
