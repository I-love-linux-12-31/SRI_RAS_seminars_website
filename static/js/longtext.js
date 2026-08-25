// Длинные аннотации.
//
// Разметка отдаёт текст целиком: без JavaScript посетитель видит всё, ничего
// не прячется. Скрипт лишь подрезает то, что заняло бы пол-экрана, и вешает
// кнопку — аннотации бывают и в три строки, и в три абзаца, а какая именно
// пришла, знает только браузер, когда её отрисует.
(function () {
  "use strict";

  // ~10 строк при базовом кегле 20px: короткую аннотацию подрезать незачем.
  var LIMIT = 340;

  function setup(node) {
    if (node.scrollHeight <= LIMIT + 40) return;

    var button = document.createElement("button");
    button.type = "button";
    button.className = "longtext__toggle";
    button.setAttribute("aria-expanded", "false");

    function collapse(yes) {
      node.classList.toggle("longtext--clipped", yes);
      button.setAttribute("aria-expanded", String(!yes));
      button.textContent = yes ? node.dataset.more : node.dataset.less;
    }

    button.addEventListener("click", function () {
      collapse(!node.classList.contains("longtext--clipped"));
    });

    collapse(true);
    node.insertAdjacentElement("afterend", button);
  }

  document.querySelectorAll("[data-longtext]").forEach(setup);
})();
