// Мелочи форм панели: добавление строк во вложенные формы (доклады,
// материалы) и переход к сводке ошибок.
//
// Прогрессивное улучшение: без JavaScript формсет всё равно отдаёт одну
// пустую строку, поэтому доклад можно добавить и так — просто по одному
// за сохранение. Скрипт лишь избавляет от лишних перезагрузок.
(function () {
  "use strict";

  // Сводка ошибок стоит над формой, но ниже шапки сайта, и на телефоне
  // остаётся за нижним краем экрана. Атрибут autofocus браузеры к элементу
  // с tabindex="-1" не применяют, поэтому фокус ставим сами: заодно сводку
  // прочитает скринридер.
  var summary = document.querySelector("[data-focus-me]");
  if (summary) summary.focus();

  function totalFormsInput(group) {
    // Django хранит счётчик в management_form рядом с группой.
    var fieldset = group.closest("fieldset") || document;
    return fieldset.querySelector('input[name$="-TOTAL_FORMS"]');
  }

  function clearValues(node) {
    // Куски, привязанные к сохранённой записи (фотографии докладчиков),
    // в пустой строке смысла не имеют.
    node.querySelectorAll("[data-clone-skip]").forEach(function (el) {
      el.remove();
    });
    node.querySelectorAll("input, select, textarea").forEach(function (field) {
      if (field.type === "hidden" && !/-(id|DELETE)$/.test(field.name)) return;
      if (field.type === "checkbox" || field.type === "radio") {
        field.checked = false;
      } else {
        field.value = "";
      }
    });
    // Ошибки предыдущей строки к новой отношения не имеют.
    node.querySelectorAll(".afield__err, .formerror").forEach(function (el) {
      el.remove();
    });
    node.querySelectorAll(".afield--error").forEach(function (el) {
      el.classList.remove("afield--error");
    });
    var kill = node.querySelector(".killswitch");
    if (kill) kill.remove();
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-add-inline]");
    if (!button) return;
    event.preventDefault();

    var fieldset = button.closest("fieldset");
    var group = fieldset.querySelector("[data-inline-group]");
    var rows = group.querySelectorAll("[data-inline]");
    var last = rows[rows.length - 1];
    if (!last) return;

    var total = totalFormsInput(group);
    var index = parseInt(total.value, 10);

    var copy = last.cloneNode(true);
    clearValues(copy);

    // Перенумеровываем все ссылки на индекс формы: name, id, for.
    var prefixPattern = new RegExp("-(\\d+)-", "g");
    copy.querySelectorAll("[name], [id], [for]").forEach(function (el) {
      ["name", "id", "for"].forEach(function (attr) {
        var value = el.getAttribute(attr);
        if (value) el.setAttribute(attr, value.replace(prefixPattern, "-" + index + "-"));
      });
    });

    group.appendChild(copy);
    total.value = index + 1;

    var first = copy.querySelector("input, textarea, select");
    if (first) first.focus();
  });
})();
