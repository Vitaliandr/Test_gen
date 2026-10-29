//тему ставим до отрисовки, иначе тёмная на секунду мигнёт светлой
(function () {
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch (e) { /* приватное окно */ }
  const dark = saved ? saved === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
