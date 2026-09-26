(function () {
  "use strict";
  // Theme switch: system -> light -> dark -> system. Without JavaScript the page follows
  // the system setting and the button stays hidden.
  var root = document.documentElement;
  var btn = document.getElementById("theme-toggle");
  var label = document.getElementById("theme-name");
  function current() {
    return root.getAttribute("data-theme") || "system";
  }
  function show() {
    if (label) label.textContent = current();
    if (btn) btn.setAttribute("aria-label", "Colour theme: " + current() + ". Change");
  }
  if (btn) {
    btn.hidden = false;
    show();
    btn.addEventListener("click", function () {
      var next = { system: "light", light: "dark", dark: "system" }[current()];
      if (next === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", next);
      try {
        if (next === "system") localStorage.removeItem("geotruth-theme");
        else localStorage.setItem("geotruth-theme", next);
      } catch (e) {}
      show();
    });
  }
  // Copy buttons on commands (progressive enhancement).
  if (navigator.clipboard) {
    var blocks = document.querySelectorAll("pre.cmd");
    for (var i = 0; i < blocks.length; i++) {
      (function (pre) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "copy";
        b.textContent = "Copy";
        b.addEventListener("click", function () {
          navigator.clipboard.writeText(pre.textContent).then(function () {
            b.textContent = "Copied";
            setTimeout(function () { b.textContent = "Copy"; }, 1500);
          });
        });
        pre.parentNode.insertBefore(b, pre);
      })(blocks[i]);
    }
  }
})();
