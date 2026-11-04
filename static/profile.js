// Perfil ativo NESTE aparelho (escolhido na tela "Quem está lendo?"), usado
// pelo index.html e pelo reader.html. Toda chamada /api/ leva o header
// X-Profile: o servidor separa estado de leitura/listas/stats por perfil e o
// service worker usa o header na chave do cache. Um X-Profile já presente
// (ex.: fila de sync offline, gravada com o perfil da época) não é sobrescrito.
let curProfile=localStorage.getItem('cs_profile')||'';
function setProfile(id){
  curProfile=id||'';
  if(id)localStorage.setItem('cs_profile',id);else localStorage.removeItem('cs_profile');
}
(()=>{
  const f=window.fetch.bind(window);
  window.fetch=(u,o={})=>{
    const url=typeof u==='string'?u:(u&&u.url)||'';
    const path=url.startsWith(location.origin)?url.slice(location.origin.length):url;
    if(curProfile&&path.startsWith('/api/')){
      const h=new Headers(o.headers||(u instanceof Request?u.headers:undefined));
      if(!h.has('X-Profile'))h.set('X-Profile',curProfile);
      o={...o,headers:h};
    }
    return f(u,o);
  };
})();
