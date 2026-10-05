// Aplica o tema (claro/escuro) antes de a página desenhar, para não piscar. "auto" segue o sistema.
(function () {
  var t = "auto";
  try { t = localStorage.getItem("quiron-tema") || "auto"; } catch (e) { /* navegador sem localStorage: segue o sistema */ }
  if (t !== "claro" && t !== "escuro") t = window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "escuro";
  document.documentElement.setAttribute("data-tema", t);
})();
