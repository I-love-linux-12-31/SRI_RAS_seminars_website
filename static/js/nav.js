// Бургер-меню на узких экранах.
//
// Прогрессивное улучшение: класс .nav--js вешает сам скрипт, и только под ним
// стили прячут пункты меню за кнопкой. Без JavaScript кнопки не видно, а пункты
// остаются на странице — просто занимают две строки, как и раньше.
(function () {
  "use strict";

  var nav = document.querySelector(".nav");
  if (!nav) return;

  var toggle = nav.querySelector("[data-nav-toggle]");
  var links = nav.querySelector(".nav__links");
  if (!toggle || !links) return;

  nav.classList.add("nav--js");

  function open(yes) {
    toggle.setAttribute("aria-expanded", String(yes));
    links.classList.toggle("nav__links--open", yes);
  }

  toggle.addEventListener("click", function () {
    open(toggle.getAttribute("aria-expanded") !== "true");
  });

  // Раскрытое меню закрывает собой начало страницы, поэтому закрываем его
  // и по клику мимо, и по Escape — как любое всплывающее окно на сайте.
  document.addEventListener("click", function (event) {
    if (!nav.contains(event.target)) open(false);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (toggle.getAttribute("aria-expanded") !== "true") return;
    open(false);
    toggle.focus();
  });
})();
