(() => {
  const btnYoutube = document.getElementById("tabBtnYoutube");
  const btnTiktok = document.getElementById("tabBtnTiktok");
  const tabYoutube = document.getElementById("tabYoutube");
  const tabTiktok = document.getElementById("tabTiktok");

  function setTab(tab) {
    const yt = tab === "youtube";
    btnYoutube.classList.toggle("active", yt);
    btnTiktok.classList.toggle("active", !yt);
    tabYoutube.classList.toggle("active", yt);
    tabTiktok.classList.toggle("active", !yt);
  }

  btnYoutube?.addEventListener("click", () => setTab("youtube"));
  btnTiktok?.addEventListener("click", () => setTab("tiktok"));

  setTab("youtube");
})();

