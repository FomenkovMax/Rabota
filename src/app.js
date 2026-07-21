import './styles.css';
import sceneCabinUrl from './assets/img/scene-cabin.webp';
import sceneTopUrl from './assets/img/scene-top.webp';

(function(){
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var floors = [
    {n:0,name:"Лобби"},
    {n:1,name:"PR-кампания"},
    {n:2,name:"Диагностика"},
    {n:3,name:"Заявка"},
    {n:4,name:"Отбор"},
    {n:5,name:"Наставник"},
    {n:6,name:"План развития"},
    {n:7,name:"Практика"},
    {n:8,name:"Аттестация"},
    {n:9,name:"Руководитель"}
  ];

  var railDots = document.getElementById('railDots');
  floors.forEach(function(f){
    var d = document.createElement('div');
    d.className = 'rail-dot';
    d.dataset.floor = f.n;
    var s = document.createElement('span');
    s.textContent = String(f.n).padStart(2,'0');
    d.appendChild(s);
    railDots.appendChild(d);
  });
  var dotEls = railDots.querySelectorAll('.rail-dot');

  var routeTrack = document.getElementById('routeTrack');
  var routeLabels = document.getElementById('routeLabels');
  var routeStages = floors.slice(1);
  if (routeTrack && routeLabels){
    routeStages.forEach(function(f,i){
      var lightness = 30 + (i / (routeStages.length - 1)) * 40;
      var seg = document.createElement('div');
      seg.className = 'route-seg';
      seg.dataset.floor = f.n;
      seg.style.background = 'hsl(38 55% ' + lightness.toFixed(0) + '%)';
      seg.title = 'Этаж ' + String(f.n).padStart(2,'0') + ' · ' + f.name;
      var n = document.createElement('span');
      n.className = 'n';
      n.textContent = String(f.n).padStart(2,'0');
      seg.appendChild(n);
      routeTrack.appendChild(seg);

      var label = document.createElement('span');
      label.dataset.floor = f.n;
      label.textContent = f.name;
      routeLabels.appendChild(label);
    });
  }
  var routeSegEls = routeTrack ? routeTrack.querySelectorAll('.route-seg') : [];
  var routeLabelEls = routeLabels ? routeLabels.querySelectorAll('span') : [];

  document.documentElement.classList.add('js-ready');

  var hudNum = document.getElementById('hudNum');
  var hudName = document.getElementById('hudName');
  var sceneLayers = document.querySelectorAll('.scene-layer');

  // cabin/top backdrops are off-screen at load: attach them lazily so the
  // first screen only pays for the lobby scene
  var sceneSrc = { cabin: sceneCabinUrl, top: sceneTopUrl };
  var scenesHydrated = false;
  function hydrateScenes(){
    if (scenesHydrated) return;
    scenesHydrated = true;
    sceneLayers.forEach(function(l){
      var src = sceneSrc[l.dataset.mood];
      if (src) l.style.backgroundImage = 'url(' + src + ')';
    });
  }
  if ('requestIdleCallback' in window) requestIdleCallback(hydrateScenes, {timeout: 2000});
  else setTimeout(hydrateScenes, 1500);
  window.addEventListener('scroll', hydrateScenes, {once: true, passive: true});

  function moodFor(n){
    if (n <= 3) return 'lobby';
    if (n <= 6) return 'cabin';
    return 'top';
  }

  function setFloor(n){
    var f = floors[n] || floors[0];
    hudNum.textContent = String(f.n).padStart(2,'0');
    hudName.textContent = f.name;
    dotEls.forEach(function(d){
      d.classList.toggle('active', Number(d.dataset.floor) === f.n);
    });
    routeSegEls.forEach(function(d){
      d.classList.toggle('active', Number(d.dataset.floor) === f.n);
    });
    routeLabelEls.forEach(function(d){
      d.classList.toggle('active', Number(d.dataset.floor) === f.n);
    });
    var mood = moodFor(f.n);
    if (mood !== 'lobby') hydrateScenes();
    sceneLayers.forEach(function(l){
      l.classList.toggle('active', l.dataset.mood === mood);
    });
  }

  var sections = document.querySelectorAll('[data-floor]');
  if ('IntersectionObserver' in window){
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(e){
        e.target.classList.toggle('is-active', e.isIntersecting);
      });
      var best = null;
      sections.forEach(function(s){
        var r = s.getBoundingClientRect();
        var visible = Math.min(r.bottom, innerHeight) - Math.max(r.top, 0);
        if (visible > 0 && (!best || visible > best.visible)){
          best = {visible: visible, floor: Number(s.dataset.floor)};
        }
      });
      if (best) setFloor(best.floor);
    }, {threshold:[0,.25,.5,.75,1]});
    var startDelay = reduceMotion ? 0 : 550;
    setTimeout(function(){
      sections.forEach(function(s){ io.observe(s); });
    }, startDelay);
  } else {
    sections.forEach(function(s){ s.classList.add('is-active'); });
  }

  var ticking = false;
  function updateProgress(){
    var max = document.body.scrollHeight - innerHeight;
    var p = max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0;
    document.documentElement.style.setProperty('--progress', p.toFixed(4));
    ticking = false;
  }
  window.addEventListener('scroll', function(){
    if (!ticking){ requestAnimationFrame(updateProgress); ticking = true; }
  }, {passive:true});
  updateProgress();
  setFloor(0);
})();
