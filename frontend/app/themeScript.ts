export const THEME_STORAGE_KEY = "locus.theme.v1";

// Re-reads storage on every OS change so a choice made after load wins; runs before paint, so keep it ES5.
export const themeScript = `(function(){var d=document.documentElement;var m=window.matchMedia("(prefers-color-scheme: dark)");function r(){var c=null;try{c=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)})}catch(e){}d.dataset.theme=c==="light"||c==="dark"?c:m.matches?"dark":"light"}r();m.addEventListener("change",r)})()`;
