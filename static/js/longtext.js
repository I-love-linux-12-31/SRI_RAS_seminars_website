// Длинные аннотации.
//
// Разметка отдаёт текст целиком: без JavaScript посетитель видит всё, ничего
// не прячется. Скрипт лишь подрезает то, что заняло бы пол-экрана, и вешает
// кнопку — аннотации бывают и в три строки, и в три абзаца, а какая именно
// пришла, знает только браузер, когда её отрисует.
//
// По кнопке аннотация открывается всплывающим блоком во всю ширину страницы:
// в колонке доклада длинному тексту тесно, а разворачивание на месте сдвигало
// вниз всё остальное — читателю приходилось искать, где он остановился.
(function () {
  "use strict";

  // ~10 строк при базовом кегле 20px: короткую аннотацию подрезать незачем.
  var LIMIT = 340;

  var sheet = document.getElementById("longtext-sheet");
  var sheetTitle = document.getElementById("longtext-sheet-title");
  var sheetBody = sheet ? sheet.querySelector("[data-sheet-body]") : null;
  var lastFocused = null;

  function sheetWorks() {
    return Boolean(sheet && sheetBody && typeof sheet.showModal === "function");
  }

  function open(node) {
    sheetTitle.textContent = node.dataset.longtextTitle || "";
    // Переносим копию: оригинал остаётся на странице подрезанным, и после
    // закрытия блока ничего восстанавливать не нужно.
    var copy = node.cloneNode(true);
    sheetBody.replaceChildren();
    while (copy.firstChild) sheetBody.appendChild(copy.firstChild);
    sheetBody.scrollTop = 0;

    lastFocused = document.activeElement;
    sheet.showModal();
  }

  function close() {
    if (sheet.open) sheet.close();
  }

  if (sheetWorks()) {
    sheet.addEventListener("click", function (event) {
      // Клик по подложке: сам <dialog> занимает всю ширину, поэтому промах
      // мимо карточки — это попадание в него самого.
      if (event.target === sheet) close();
      if (event.target.closest("[data-close-sheet]")) close();
    });

    sheet.addEventListener("close", function () {
      sheetBody.replaceChildren();
      if (lastFocused && lastFocused.focus) lastFocused.focus();
    });
  }

  function setup(node) {
    // data-longtext-hide: текст прячется целиком и открывается только кнопкой.
    // Длину при этом не меряем — иначе у одного доклада на странице была бы
    // аннотация, у соседнего кнопка, и список докладов выглядел бы вразнобой.
    var hidden = "longtextHide" in node.dataset;
    if (!hidden && node.scrollHeight <= LIMIT + 40) return;

    var folded = hidden ? "longtext--hidden" : "longtext--clipped";

    var button = document.createElement("button");
    button.type = "button";
    button.className = "longtext__toggle";
    button.textContent = node.dataset.more;

    if (sheetWorks()) {
      node.classList.add(folded);
      button.addEventListener("click", function () {
        open(node);
      });
    } else {
      // Браузер без <dialog>: остаётся прежнее разворачивание на месте.
      button.setAttribute("aria-expanded", "false");

      function collapse(yes) {
        node.classList.toggle(folded, yes);
        button.setAttribute("aria-expanded", String(!yes));
        button.textContent = yes ? node.dataset.more : node.dataset.less;
      }

      button.addEventListener("click", function () {
        collapse(!node.classList.contains(folded));
      });
      collapse(true);
    }

    node.insertAdjacentElement("afterend", button);
  }

  document.querySelectorAll("[data-longtext]").forEach(setup);
})();
