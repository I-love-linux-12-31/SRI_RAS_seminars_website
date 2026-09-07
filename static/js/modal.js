// Модальное окно записи на нативном <dialog>.
//
// Это прогрессивное улучшение: ссылка «Записаться» ведёт на полноценную
// страницу формы и работает без JavaScript. Скрипт лишь перехватывает клик
// и показывает ту же форму в диалоге. Нативный <dialog> сам даёт focus trap,
// закрытие по Escape и корректную семантику для скринридеров.
(function () {
  "use strict";

  var dialog = document.getElementById("reg-dialog");
  if (!dialog) return;

  var slot = document.getElementById("regform-slot");
  var lastFocused = null;

  function open(url) {
    lastFocused = document.activeElement;
    dialog.showModal();
    if (window.htmx) {
      window.htmx.ajax("GET", url, { target: "#regform-slot", swap: "innerHTML" });
    }
  }

  function close() {
    if (dialog.open) dialog.close();
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-open-register]");
    if (trigger) {
      // Без htmx отдаём браузеру уйти на страницу формы.
      if (!window.htmx) return;
      event.preventDefault();
      open(trigger.getAttribute("href"));
      return;
    }

    if (event.target.closest("[data-close-modal]")) {
      event.preventDefault();
      close();
    }
  });

  // Клик по подложке за пределами карточки закрывает окно.
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) close();
  });

  dialog.addEventListener("close", function () {
    if (slot) slot.replaceChildren();
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  });

  // Формат участия управляет блоками, которые касаются только очного участия:
  // гражданства и подсказки про пропуск.
  document.addEventListener("change", function (event) {
    if (event.target.name !== "attendance") return;
    var online = event.target.value !== "onsite";
    document.querySelectorAll("[data-onsite-only]").forEach(function (block) {
      block.hidden = online;
    });
  });
})();
