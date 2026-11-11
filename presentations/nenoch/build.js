// Презентация «Неночь» (Nevernight) Джея Кристоффа
// Тёмная готика, 13 слайдов, без спойлеров, формат под публичное выступление.
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const Gi = require("react-icons/gi");

// ── Палитра ───────────────────────────────────────────────────────────────
const BG = "0B0910";
const CARD = "16121E";
const CARD2 = "1C1727";
const LINE = "2C2438";
const BONE = "EDE6D9";
const MUTED = "9891A6";
const DIM = "6E6880";
const RED = "A4161A";
const RED_BR = "D8484B";
const GOLD = "C9A961";

const SERIF = "Cambria";
const SANS = "Calibri";

const W = 13.333;
const H = 7.5;
const M = 0.7;
const CW = W - M * 2;

// ── Иконки ────────────────────────────────────────────────────────────────
async function icon(name, color, px = 256) {
  const Comp = Gi[name];
  if (!Comp) throw new Error("Нет иконки: " + name);
  let svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color: "#" + color, size: px })
  );
  if (!svg.includes("xmlns=")) svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  const buf = await sharp(Buffer.from(svg), { density: 300 }).resize(px, px).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

const ICONS = {};
async function loadIcons() {
  const need = {
    steel: ["GiTwoHandedSword", GOLD],
    poison: ["GiPoisonBottle", GOLD],
    mask: ["GiTribalMask", GOLD],
    pocket: ["GiSwapBag", GOLD],
    cat: ["GiHollowCat", GOLD],
    shadows: ["GiShadowGrasp", GOLD],
    daggers: ["GiDaggers", GOLD],
    flame: ["GiFlame", RED_BR],
    crown: ["GiJewelCrown", RED_BR],
    sprout: ["GiSprout", RED_BR],
    yin: ["GiYinYang", RED_BR],
    quill: ["GiQuillInk", GOLD],
    hourglass: ["GiHourglass", GOLD],
    skull: ["GiSpadeSkull", GOLD],
    scroll: ["GiScrollUnfurled", GOLD],
    laurel: ["GiLaurelsTrophy", GOLD],
    raven: ["GiRaven", GOLD],
  };
  for (const [k, [n, c]] of Object.entries(need)) ICONS[k] = await icon(n, c);
}

// ── Примитивы ─────────────────────────────────────────────────────────────
const pres = new pptxgen();

function newSlide(num) {
  const s = pres.addSlide();
  s.background = { color: BG };
  if (num) {
    // мотив: три солнца
    s.addShape(pres.ShapeType.ellipse, { x: 12.03, y: 0.41, w: 0.1, h: 0.1, fill: { color: RED } });
    s.addShape(pres.ShapeType.ellipse, { x: 12.23, y: 0.39, w: 0.14, h: 0.14, fill: { color: GOLD } });
    s.addShape(pres.ShapeType.ellipse, { x: 12.47, y: 0.42, w: 0.08, h: 0.08, fill: { color: DIM } });
    s.addText(String(num).padStart(2, "0"), {
      x: 11.63, y: 6.82, w: 0.99, h: 0.3, isTextBox: true, margin: 0,
      align: "right", fontFace: SANS, fontSize: 10, color: DIM, charSpacing: 2,
    });
  }
  return s;
}

function eyebrow(s, text) {
  s.addText(text, {
    x: M, y: 0.46, w: 8, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, bold: true, color: GOLD, charSpacing: 4,
  });
}

function title(s, text, opts = {}) {
  s.addText(text, {
    x: M, y: opts.y || 0.82, w: opts.w || 10.0, h: opts.h || 0.9, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: opts.size || 40, bold: true, color: BONE, valign: "top",
  });
}

function card(s, x, y, w, h, fill = CARD) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: fill }, line: { color: LINE, width: 1 },
  });
}

function iconCircle(s, x, y, d, key, bg = CARD2) {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: bg }, line: { color: LINE, width: 1 } });
  const pad = d * 0.26;
  s.addImage({ data: ICONS[key], x: x + pad, y: y + pad, w: d - pad * 2, h: d - pad * 2 });
}

function body(s, text, x, y, w, h, opts = {}) {
  s.addText(text, {
    x, y, w, h, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: opts.size || 14, color: opts.color || MUTED,
    lineSpacingMultiple: opts.lsm || 1.25, valign: opts.valign || "top", align: opts.align || "left",
    bold: opts.bold || false, italic: opts.italic || false, charSpacing: opts.cs || 0,
  });
}

function head(s, text, x, y, w, h, opts = {}) {
  s.addText(text, {
    x, y, w, h, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: opts.size || 20, bold: true, color: opts.color || BONE, valign: "top",
  });
}

// ══════════════════════════════════════════════════════════════════════════
async function build() {
  await loadIcons();
  pres.layout = "LAYOUT_WIDE";
  pres.author = "Максим";
  pres.title = "Неночь — Джей Кристофф";

  // ── 1. Титул ────────────────────────────────────────────────────────────
  {
    const s = newSlide(null);
    s.background = { color: BG };
    // большие «три солнца» справа
    s.addShape(pres.ShapeType.ellipse, { x: 9.15, y: 1.35, w: 3.5, h: 3.5, fill: { color: "120E1A" }, line: { color: "241D30", width: 1 } });
    s.addShape(pres.ShapeType.ellipse, { x: 10.05, y: 2.25, w: 1.7, h: 1.7, fill: { color: "1B1424" }, line: { color: RED, width: 1 } });
    s.addShape(pres.ShapeType.ellipse, { x: 10.62, y: 2.82, w: 0.56, h: 0.56, fill: { color: GOLD } });
    s.addShape(pres.ShapeType.ellipse, { x: 9.62, y: 1.82, w: 0.2, h: 0.2, fill: { color: RED_BR } });
    s.addShape(pres.ShapeType.ellipse, { x: 11.85, y: 4.05, w: 0.13, h: 0.13, fill: { color: MUTED } });

    s.addText("ТЁМНОЕ ФЭНТЕЗИ · 2016", {
      x: M, y: 1.5, w: 7, h: 0.32, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 12, bold: true, color: GOLD, charSpacing: 6,
    });
    s.addText("НЕНОЧЬ", {
      x: M, y: 1.95, w: 8, h: 1.5, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 92, bold: true, color: BONE, charSpacing: 2,
    });
    s.addText("N E V E R N I G H T", {
      x: M + 0.05, y: 3.42, w: 8, h: 0.4, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 16, color: RED_BR, charSpacing: 6,
    });
    s.addText("Джей Кристофф", {
      x: M, y: 4.25, w: 7, h: 0.45, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 26, color: BONE,
    });
    body(s, "Первая книга «Хроник Неночи»\nРусское издание — АСТ, перевод А. Харченко", M, 4.8, 7, 0.8, { size: 14 });
    body(s, "Разбор без спойлеров", M, 6.55, 6, 0.35, { size: 12, color: DIM, cs: 3 });
    s.addNotes(
      "Начало: 'Представьте мир, в котором почти никогда не бывает темно. А теперь представьте школу, где темнотой убивают.'\n" +
      "Это «Неночь» Джея Кристоффа, 2016 год, тёмное фэнтези для взрослых. Первая книга трилогии.\n" +
      "Сразу договоримся: спойлеров не будет — я расскажу про мир, героев и стиль, а финал оставлю вам."
    );
  }

  // ── 2. О чём это ────────────────────────────────────────────────────────
  {
    const s = newSlide(2);
    eyebrow(s, "О ЧЁМ ЭТО");
    s.addText("Мир, где ночь наступает раз в два с половиной года.\nИ школа, где из этой темноты делают оружие.", {
      x: M, y: 1.35, w: 7.4, h: 2.5, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 32, bold: true, color: BONE, lineSpacingMultiple: 1.15,
    });
    body(s,
      "Шестнадцатилетняя Мия Корвере приходит в Красную Церковь — школу убийц — не за знаниями. " +
      "Её отца казнили за проигранное восстание, семью уничтожили. Она хочет отомстить и готова заплатить за это чем угодно.",
      M, 4.15, 7.4, 1.6, { size: 16, lsm: 1.3 });

    card(s, 8.55, 1.3, 4.08, 4.7, CARD);
    iconCircle(s, 9.09, 1.85, 1.0, "daggers");
    head(s, "Формула книги", 8.95, 3.05, 3.3, 0.4, { size: 18 });
    body(s,
      "Школа убийц\n+ мир трёх солнц\n+ месть без иллюзий\n+ рассказчик в сносках",
      8.95, 3.6, 3.4, 2.1, { size: 15, lsm: 1.4 });
    s.addNotes(
      "Одной фразой: это история мести, упакованная в жанр «школа убийц».\n" +
      "Ключевая деталь мира вынесена в название: неночь — состояние, когда настоящей ночи почти не бывает.\n" +
      "Мия идёт в Красную Церковь ради конкретной цели, а не ради приключений. Это не сказка о взрослении — это про цену."
    );
  }

  // ── 3. Автор ────────────────────────────────────────────────────────────
  {
    const s = newSlide(3);
    eyebrow(s, "АВТОР");
    title(s, "Джей Кристофф");

    card(s, M, 1.75, 5.7, 4.35);
    iconCircle(s, M + 0.45, 2.2, 0.9, "raven");
    head(s, "Кто это", M + 0.45, 3.35, 4.8, 0.35, { size: 18 });
    body(s,
      "Австралийский писатель из Мельбурна. Тёмное фэнтези и научная фантастика для взрослых.\n\nФирменный почерк: жестокость без романтизации, чёрный юмор и плотный, ритмичный язык.",
      M + 0.45, 3.8, 4.9, 2.05, { size: 15, lsm: 1.28 });

    const books = [
      ["«Танцующая с бурей»", "Stormdancer, 2012 — японское стимпанк-фэнтези"],
      ["«Иллюминае»", "Illuminae, 2015 — космическая НФ в соавторстве с Эми Кауфман"],
      ["«Империя вампиров»", "Empire of the Vampire, 2021 — тёмное фэнтези"],
    ];
    let by = 1.75;
    books.forEach(([t, d]) => {
      card(s, 6.85, by, 5.78, 1.28, CARD2);
      head(s, t, 7.2, by + 0.22, 5.1, 0.35, { size: 17 });
      body(s, d, 7.2, by + 0.65, 5.1, 0.5, { size: 13 });
      by += 1.535;
    });
    s.addNotes(
      "Кристофф — австралиец, пишет много и в разных жанрах.\n" +
      "Важно: он не «милый» автор. Если ждёте уютное фэнтези — это не сюда.\n" +
      "Если читали «Иллюминае» — там он экспериментировал с формой подачи. В «Неночи» эксперимент другой: сноски."
    );
  }

  // ── 4. Мир ──────────────────────────────────────────────────────────────
  {
    const s = newSlide(4);
    eyebrow(s, "МИР");
    title(s, "Итрея: мир трёх солнц");

    // схема трёх солнц
    card(s, M, 1.8, 3.55, 4.3, CARD);
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.75, y: 2.25, w: 1.5, h: 1.5, fill: { color: GOLD } });
    s.addShape(pres.ShapeType.ellipse, { x: M + 2.15, y: 2.75, w: 0.75, h: 0.75, fill: { color: RED } });
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.5, y: 3.55, w: 0.42, h: 0.42, fill: { color: RED_BR } });
    body(s, "Три светила на небе.\nПолная темнота — событие,\nа не время суток.", M + 0.35, 4.5, 2.9, 1.2,
      { size: 14, align: "center" });

    const facts = [
      ["Неночь", "Почти весь год над Итреей висит хотя бы одно солнце. Тени коротки, спрятаться негде, а «ночь» — понятие условное."],
      ["Истинная тьма", "Примерно раз в два с половиной года все три солнца гаснут разом. Настоящая ночь возвращается — и вместе с ней возвращается то, что живёт в тени."],
      ["Республика", "Сенат, консул, кланы, долги и кровная вражда. Политика здесь убивает не реже клинка — и куда изящнее."],
    ];
    let fy = 1.8;
    facts.forEach(([t, d]) => {
      card(s, 4.6, fy, 8.03, 1.38, CARD2);
      head(s, t, 4.95, fy + 0.18, 7.3, 0.35, { size: 18, color: GOLD });
      body(s, d, 4.95, fy + 0.6, 7.3, 0.72, { size: 13, lsm: 1.18 });
      fy += 1.5;
    });
    s.addNotes(
      "Главная придумка мира вынесена в заголовок книги.\n" +
      "Три солнца — значит темнота дефицит. Для убийцы, который работает тенями, это не декорация, а рабочая проблема.\n" +
      "Истинная тьма — редкое событие, к нему в книге привязана и религия, и календарь, и сюжет.\n" +
      "Итрея — это очень узнаваемый Древний Рим: сенат, консул, интриги. Кристофф этого и не скрывает."
    );
  }

  // ── 5. Завязка ──────────────────────────────────────────────────────────
  {
    const s = newSlide(5);
    eyebrow(s, "ЗАВЯЗКА");
    title(s, "С чего всё начинается");

    s.addShape(pres.ShapeType.roundRect, {
      x: 10.35, y: 0.82, w: 2.28, h: 0.42, rectRadius: 0.08,
      fill: { color: "1E1218" }, line: { color: RED, width: 1 },
    });
    s.addText("БЕЗ СПОЙЛЕРОВ", {
      x: 10.35, y: 0.82, w: 2.28, h: 0.42, isTextBox: true, margin: 0,
      align: "center", valign: "middle", fontFace: SANS, fontSize: 11, bold: true, color: RED_BR, charSpacing: 3,
    });

    const steps = [
      ["01", "Казнь", "Отец Мии возглавил восстание, проиграл и был публично казнён. Семью уничтожили. Девочке было шесть."],
      ["02", "Шесть лет", "Её прячет и растит Меркурио — старый отравитель с лавкой и тяжёлым характером. Он учит её клинку, яду и главному: терпению."],
      ["03", "Красная Церковь", "Мия поступает в школу убийц, чтобы получить право на месть. Испытание длиной в год. Клинками станут единицы."],
    ];
    let x = M;
    steps.forEach(([n, t, d]) => {
      card(s, x, 1.9, 3.78, 3.9);
      s.addText(n, {
        x: x + 0.4, y: 2.15, w: 1.5, h: 0.8, isTextBox: true, margin: 0,
        fontFace: SERIF, fontSize: 52, bold: true, color: RED,
      });
      head(s, t, x + 0.4, 3.0, 3.0, 0.78, { size: 21 });
      body(s, d, x + 0.4, 3.82, 3.05, 1.85, { size: 13.5, lsm: 1.22 });
      x += 4.075;
    });
    body(s, "Дальше начинается собственно книга — и вот об этом я молчу.", M, 6.1, 9, 0.4, { size: 14, italic: true, color: DIM });
    s.addNotes(
      "Три шага — и мы у входа в основной сюжет.\n" +
      "Обратите внимание: месть здесь не спонтанная вспышка. Мия шла к ней десять лет.\n" +
      "Меркурио — важная фигура: циничный старик, который заменил ей отца, но никогда не притворялся добрым.\n" +
      "Всё, что дальше — испытания в Церкви и финал — оставляю вам. Скажу только: книга не жалеет никого."
    );
  }

  // ── 6. Красная Церковь ──────────────────────────────────────────────────
  {
    const s = newSlide(6);
    eyebrow(s, "КРАСНАЯ ЦЕРКОВЬ");
    title(s, "Четыре дисциплины");

    const disc = [
      ["steel", "Сталь", "Бой и оружие. Как убить, если дошло до прямого столкновения."],
      ["poison", "Яды", "Химия, травы, дозировки. Как убить так, чтобы это выглядело болезнью."],
      ["mask", "Маски", "Обман, роли, обольщение. Как подойти к цели вплотную и остаться никем."],
      ["pocket", "Карманы", "Воровство и скрытность. Как войти туда, куда нельзя, и выйти живым."],
    ];
    const cx = [M, 6.85];
    const cy = [1.8, 3.72];
    disc.forEach((d, i) => {
      const X = cx[i % 2], Y = cy[Math.floor(i / 2)];
      card(s, X, Y, 5.78, 1.78);
      iconCircle(s, X + 0.35, Y + 0.36, 1.05, d[0]);
      head(s, d[1], X + 1.62, Y + 0.35, 3.9, 0.4, { size: 21 });
      body(s, d[2], X + 1.62, Y + 0.87, 3.9, 0.8, { size: 13.5, lsm: 1.2 });
    });
    body(s,
      "У каждой дисциплины свой наставник. Над всеми — Преподобная Матерь Друзилла. Учеников много, мест мало, а отчисление здесь редко бывает мирным.",
      M, 5.78, 11.93, 0.6, { size: 14, italic: true, color: DIM, lsm: 1.2 });
    s.addNotes(
      "Красная Церковь — не метафора, а действующий культ со своей школой.\n" +
      "Четыре дисциплины — это по сути четыре способа решить одну задачу. Ученики проходят все.\n" +
      "Важный момент атмосферы: это не Хогвартс. Конкуренция здесь буквально смертельная, и книга напоминает об этом регулярно.\n" +
      "Если аудитория спросит про имена наставников — их четверо, у каждого своя специализация и очень разный характер."
    );
  }

  // ── 7. Мия ──────────────────────────────────────────────────────────────
  {
    const s = newSlide(7);
    eyebrow(s, "ГЕРОИНЯ");
    title(s, "Мия Корвере");

    card(s, M, 1.8, 4.3, 4.3, CARD);
    iconCircle(s, M + 1.25, 2.25, 1.8, "shadows", "221B2E");
    body(s, "МИЯ КОРВЕРЕ", M + 0.4, 4.35, 3.5, 0.35, { size: 13, bold: true, color: GOLD, cs: 3, align: "center" });
    body(s, "16 лет. Аколит Красной Церкви.\nПовелевает тенями.", M + 0.4, 4.8, 3.5, 0.9,
      { size: 14, align: "center", lsm: 1.2 });

    const traits = [
      ["Даркин", "Тени слушаются её: гасят свет, глушат звук, прячут. Это врождённое, и это ненормально даже по меркам Итреи."],
      ["Мотив", "Месть людям, которые стояли за казнью её отца. Не абстрактное зло — конкретные имена и лица."],
      ["Характер", "Умная, злая, упрямая. Не «хорошая девочка» и не собирается ею становиться — книга не пытается её оправдать."],
      ["Цена", "За силу она платит. Не деньгами и не кровью врагов — тем, что теряет по дороге."],
    ];
    let ty = 1.8;
    traits.forEach(([t, d]) => {
      card(s, 5.35, ty, 7.28, 1.0, CARD2);
      head(s, t, 5.7, ty + 0.15, 1.75, 0.35, { size: 17, color: GOLD });
      body(s, d, 7.5, ty + 0.16, 4.8, 0.75, { size: 13, lsm: 1.15 });
      ty += 1.1;
    });
    s.addNotes(
      "Мия — не «сильная женская героиня» из шаблона. Она мстительная, часто неправа и делает жестокие вещи.\n" +
      "Даркин — редкий дар управлять тенями. В мире трёх солнц это одновременно суперсила и клеймо.\n" +
      "Ключ к персонажу — четвёртый пункт: сила у неё не бесплатная. Как именно она платит — узнаете сами.\n" +
      "Именно поэтому книга взрослая: героине не выдают моральных индульгенций."
    );
  }

  // ── 8. Мистер Добряк ────────────────────────────────────────────────────
  {
    const s = newSlide(8);
    eyebrow(s, "СПУТНИК");
    title(s, "Мистер Добряк");

    card(s, 7.5, 1.8, 5.13, 4.3, CARD);
    iconCircle(s, 8.9, 2.2, 2.3, "cat", "221B2E");
    body(s, "MISTER KINDLY", 7.85, 4.75, 4.4, 0.35, { size: 13, bold: true, color: GOLD, cs: 3, align: "center" });
    body(s, "Кот, которого нет.", 7.85, 5.2, 4.4, 0.4, { size: 15, italic: true, align: "center" });

    body(s,
      "Тень в форме кота. Разговаривает. Язвит. Комментирует всё, что делает Мия, — и почти всегда неудобно.",
      M, 1.85, 6.4, 1.0, { size: 17, color: BONE, lsm: 1.25 });

    const pts = [
      ["Ест страх", "Буквально. Рядом с ним Мии не страшно — а страх в этой школе убивает первым."],
      ["Голос со стороны", "Он спорит, ехидничает и говорит вслух то, что Мия предпочла бы не думать."],
      ["Напоминание о цене", "Ничего не даётся даром. Он забирает страх — и вместе с ним кое-что ещё."],
    ];
    let py = 3.0;
    pts.forEach(([t, d]) => {
      card(s, M, py, 6.4, 1.05, CARD2);
      head(s, t, M + 0.32, py + 0.16, 2.05, 0.7, { size: 16, color: GOLD });
      body(s, d, M + 2.55, py + 0.16, 3.55, 0.8, { size: 12.5, lsm: 1.15 });
      py += 1.13;
    });
    s.addNotes(
      "Мистер Добряк — визитная карточка книги. Многие читатели приходят за Мией, а остаются за котом.\n" +
      "Механика простая и умная: он ест её страх. Значит, героиня объективно бесстрашна — но не потому, что смелая.\n" +
      "И это ровно тот случай, когда приятная деталь оказывается частью большой темы: за всё платят.\n" +
      "Если хотите одну причину прочитать книгу — вот она сидит на плече у героини."
    );
  }

  // ── 9. Окружение ────────────────────────────────────────────────────────
  {
    const s = newSlide(9);
    eyebrow(s, "ОКРУЖЕНИЕ");
    title(s, "Кто рядом с ней");

    const people = [
      ["М", "Меркурио", "Наставник", "Старый отравитель с лавкой диковин. Спрятал Мию после казни отца и вырастил из неё оружие. Ворчлив, циничен, предан — в таком порядке."],
      ["Т", "Трик", "Аколит", "Полукровка-двеймери с татуировками на лице. Гордый, вспыльчивый, чужой в этой школе примерно так же, как Мия."],
      ["Э", "Эшлин", "Аколит", "Девушка из семьи, где ремесло убийцы передают по наследству. Обаятельная, острая на язык и очень себе на уме."],
    ];
    let x = M;
    people.forEach(([ini, name, role, d]) => {
      card(s, x, 1.8, 3.78, 3.95);
      s.addShape(pres.ShapeType.ellipse, {
        x: x + 0.4, y: 2.15, w: 0.95, h: 0.95,
        fill: { color: CARD2 }, line: { color: GOLD, width: 1 },
      });
      s.addText(ini, {
        x: x + 0.4, y: 2.15, w: 0.95, h: 0.95, isTextBox: true, margin: 0,
        align: "center", valign: "middle", fontFace: SERIF, fontSize: 30, bold: true, color: GOLD,
      });
      head(s, name, x + 0.4, 3.3, 3.0, 0.4, { size: 22 });
      body(s, role.toUpperCase(), x + 0.4, 3.78, 3.0, 0.3, { size: 11, color: RED_BR, bold: true, cs: 3 });
      body(s, d, x + 0.4, 4.15, 3.0, 1.45, { size: 13, lsm: 1.25 });
      x += 4.075;
    });
    s.addNotes(
      "Три фигуры, которые держат книгу вокруг Мии.\n" +
      "Меркурио — прошлое. Он дал ей инструменты и заодно объяснил, что мир никому ничего не должен.\n" +
      "Трик и Эшлин — настоящее: соученики, то есть одновременно друзья и конкуренты. В школе, где мест мало, это неудобная комбинация.\n" +
      "Про их линии подробно не рассказываю — там как раз лежит половина сюрпризов книги."
    );
  }

  // ── 10. Темы ────────────────────────────────────────────────────────────
  {
    const s = newSlide(10);
    eyebrow(s, "ТЕМЫ");
    title(s, "О чём книга на самом деле");

    const themes = [
      ["flame", "Месть и её цена", "Месть здесь не катарсис, а работа. Долгая, грязная и забирающая по кусочку того, кто ею занят."],
      ["crown", "Власть и политика", "Республика, сенат, кланы. Насилие показано как продолжение политики другими средствами — и наоборот."],
      ["sprout", "Взросление через жестокость", "Классический сюжет о школе, вывернутый наизнанку: оценка за экзамен здесь — жизнь."],
      ["yin", "Свет и тьма", "Тьма — не зло, свет — не добро. Книга методично ломает эту привычку и не даёт удобных ярлыков."],
    ];
    let y = 1.75;
    themes.forEach(([ic, t, d]) => {
      card(s, M, y, 11.93, 1.08, CARD);
      iconCircle(s, M + 0.28, y + 0.19, 0.7, ic);
      head(s, t, M + 1.2, y + 0.17, 3.6, 0.4, { size: 18 });
      body(s, d, M + 5.0, y + 0.2, 6.6, 0.7, { size: 13.5, lsm: 1.15 });
      y += 1.2;
    });
    s.addNotes(
      "Если снять с книги жанровую упаковку, останется разговор о цене.\n" +
      "Месть — центральная тема, и Кристофф последовательно показывает, что она стоит дорого.\n" +
      "Политический слой — это фактически Рим: сенат, консул, борьба кланов.\n" +
      "И главное — отказ от простой морали. Тени в этой книге не «плохие», а свет далеко не спасение."
    );
  }

  // ── 11. Приёмы ──────────────────────────────────────────────────────────
  {
    const s = newSlide(11);
    eyebrow(s, "СТИЛЬ");
    title(s, "Приёмы Кристоффа");

    card(s, M, 1.8, 6.15, 2.6, CARD);
    iconCircle(s, M + 0.35, 2.1, 0.8, "quill");
    head(s, "Сноски-рассказчик", M + 1.4, 2.12, 4.5, 0.4, { size: 20 });
    body(s,
      "Невидимый рассказчик комментирует историю внизу страницы: объясняет устройство мира, шутит, спорит с текстом. " +
      "Это главная фирменная черта — и самый спорный приём книги.",
      M + 0.35, 3.05, 5.45, 1.2, { size: 13.5, lsm: 1.2 });

    // имитация сноски
    card(s, 7.25, 1.8, 5.38, 2.6, "120E1A");
    body(s, "…тени послушались её.", 7.6, 2.05, 4.7, 0.4, { size: 15, color: BONE });
    s.addShape(pres.ShapeType.line, { x: 7.6, y: 2.65, w: 1.6, h: 0, line: { color: LINE, width: 1 } });
    body(s, "1.  А вот это, дорогой читатель, стоило бы\n    объяснить подробнее — но объяснять\n    придётся долго, а вы и так торопитесь.",
      7.6, 2.85, 4.7, 1.2, { size: 12, italic: true, color: DIM, lsm: 1.2 });
    body(s, "Так это выглядит на странице (пример оформления)", 7.6, 3.95, 4.7, 0.3, { size: 10, color: DIM });

    const more = [
      ["hourglass", "Две линии времени", "Настоящее в Церкви чередуется с детством Мии — прошлое подаётся дозами."],
      ["skull", "Чёрный юмор", "Шутки на фоне трупов. Это тон книги, а не случайные вставки."],
      ["scroll", "Плотный язык", "Много метафор и ритма. Вход медленный — первые главы придётся перетерпеть."],
    ];
    let x = M;
    more.forEach(([ic, t, d]) => {
      card(s, x, 4.62, 3.87, 1.75, CARD2);
      iconCircle(s, x + 0.3, 4.87, 0.62, ic);
      head(s, t, x + 1.1, 4.92, 2.65, 0.35, { size: 15 });
      body(s, d, x + 0.3, 5.62, 3.27, 0.65, { size: 12, lsm: 1.15 });
      x += 4.03;
    });
    s.addNotes(
      "Вот здесь книга делит читателей пополам.\n" +
      "Сноски: у Кристоффа внизу страницы живёт отдельный голос — он объясняет мир и постоянно язвит. Одних это влюбляет, других выбешивает, потому что рвёт темп чтения. Пример справа — это моя иллюстрация приёма, а не цитата.\n" +
      "Две временные линии: прошлое Мии подаётся вставками, поэтому первые сто страниц идут медленно.\n" +
      "Честное предупреждение слушателям: если не зашли первые две главы — дайте книге ещё сто страниц, дальше темп резко растёт."
    );
  }

  // ── 12. Приём и критика ─────────────────────────────────────────────────
  {
    const s = newSlide(12);
    eyebrow(s, "ПРИЁМ И КРИТИКА");
    title(s, "Как книгу встретили");

    const stats = [
      ["Aurealis", "Премия 2016 года\nза лучший фэнтези-роман"],
      ["4,5 / 5", "Оценка читателей\nна LiveLib"],
      ["7,6 / 10", "Оценка читателей\nна «Фантлабе»"],
      ["18+", "Жестокость\nи откровенные сцены"],
    ];
    let x = M;
    stats.forEach(([n, d], i) => {
      card(s, x, 1.75, 2.83, 1.55, CARD);
      s.addText(n, {
        x: x + 0.2, y: 1.88, w: 2.43, h: 0.62, isTextBox: true, margin: 0,
        align: "center", fontFace: SERIF, fontSize: i === 0 ? 30 : 34, bold: true, color: i === 3 ? RED_BR : GOLD,
      });
      body(s, d, x + 0.2, 2.58, 2.43, 0.62, { size: 11.5, align: "center", lsm: 1.15 });
      x += 3.03;
    });

    card(s, M, 3.62, 5.85, 2.35, CARD2);
    head(s, "За что хвалят", M + 0.35, 3.85, 4.5, 0.4, { size: 19, color: GOLD });
    s.addText(
      [
        { text: "оригинальный мир трёх солнц", options: { bullet: true, breakLine: true } },
        { text: "героиня без розовых очков", options: { bullet: true, breakLine: true } },
        { text: "язык, ритм и атмосфера", options: { bullet: true, breakLine: true } },
        { text: "чёрный юмор рассказчика", options: { bullet: true } },
      ],
      { x: M + 0.4, y: 4.38, w: 5.1, h: 1.45, isTextBox: true, margin: 0, fontFace: SANS, fontSize: 13.5, color: MUTED, paraSpaceAfter: 6 }
    );

    card(s, 6.78, 3.62, 5.85, 2.35, CARD2);
    head(s, "За что ругают", 7.13, 3.85, 4.5, 0.4, { size: 19, color: RED_BR });
    s.addText(
      [
        { text: "медленный старт: первые главы вязкие", options: { bullet: true, breakLine: true } },
        { text: "сноски рвут темп чтения", options: { bullet: true, breakLine: true } },
        { text: "жестокость и откровенные сцены не для всех", options: { bullet: true, breakLine: true } },
        { text: "много терминов на входе", options: { bullet: true } },
      ],
      { x: 7.18, y: 4.38, w: 5.1, h: 1.45, isTextBox: true, margin: 0, fontFace: SANS, fontSize: 13.5, color: MUTED, paraSpaceAfter: 6 }
    );

    body(s, "Также: номинация на David Gemmell Legend Award (2017) и на Deutscher Phantastik Preis (2018, лучший переводной роман).",
      M, 6.2, 11.93, 0.4, { size: 11.5, color: DIM });
    s.addNotes(
      "Книга не единогласно хорошая — и это нормально.\n" +
      "Главная объективная награда: Aurealis Award 2016 за лучший фэнтези-роман. Плюс номинации Gemmell и немецкая премия за перевод.\n" +
      "Оценки читателей высокие, но разброс большой: люди либо влюбляются, либо бросают на первой сотне страниц.\n" +
      "Пометка 18+ не для красоты: в книге есть и жестокость, и откровенные сцены. Это стоит сказать вслух перед тем, как советовать книгу кому-то."
    );
  }

  // ── 13. Итог ────────────────────────────────────────────────────────────
  {
    const s = newSlide(13);
    eyebrow(s, "ИТОГ");
    title(s, "Читать или нет");

    card(s, M, 1.75, 5.85, 2.5, CARD);
    head(s, "Стоит читать, если", M + 0.35, 1.97, 5.0, 0.4, { size: 19, color: GOLD });
    s.addText(
      [
        { text: "любите тёмное фэнтези без утешений", options: { bullet: true, breakLine: true } },
        { text: "нравятся антигероини и мораль в серых тонах", options: { bullet: true, breakLine: true } },
        { text: "цените необычную форму подачи", options: { bullet: true } },
      ],
      { x: M + 0.4, y: 2.5, w: 5.1, h: 1.6, isTextBox: true, margin: 0, fontFace: SANS, fontSize: 13.5, color: MUTED, paraSpaceAfter: 7 }
    );

    card(s, 6.78, 1.75, 5.85, 2.5, CARD);
    head(s, "Лучше пройти мимо, если", 7.13, 1.97, 5.0, 0.4, { size: 19, color: RED_BR });
    s.addText(
      [
        { text: "не переносите жестокость и сцены 18+", options: { bullet: true, breakLine: true } },
        { text: "нужен быстрый старт с первой страницы", options: { bullet: true, breakLine: true } },
        { text: "раздражают сноски и авторские приёмы", options: { bullet: true } },
      ],
      { x: 7.18, y: 2.5, w: 5.1, h: 1.6, isTextBox: true, margin: 0, fontFace: SANS, fontSize: 13.5, color: MUTED, paraSpaceAfter: 7 }
    );

    body(s, "ТРИЛОГИЯ", M, 4.5, 4, 0.3, { size: 11, bold: true, color: GOLD, cs: 4 });
    const trio = [["Неночь", "2016"], ["Годсгрейв", "2017"], ["Тёмный рассвет", "2019"]];
    let x = M;
    trio.forEach(([t, y], i) => {
      card(s, x, 4.88, 3.4, 1.02, CARD2);
      head(s, t, x + 0.35, 5.0, 2.7, 0.35, { size: 17 });
      body(s, y, x + 0.35, 5.42, 2.7, 0.3, { size: 12, color: GOLD });
      if (i < 2) {
        s.addText("→", {
          x: x + 3.4, y: 4.88, w: 0.85, h: 1.02, isTextBox: true, margin: 0,
          align: "center", valign: "middle", fontFace: SANS, fontSize: 20, color: DIM,
        });
      }
      x += 4.25;
    });

    s.addText("Темнота здесь не враг. Темнота здесь — инструмент.", {
      x: M, y: 6.25, w: 11.93, h: 0.5, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 22, italic: true, color: BONE,
    });
    s.addNotes(
      "Резюме: книга не для всех, и это её сильная сторона — она точно знает, для кого написана.\n" +
      "Если человек любит тёмное фэнтези и не ждёт удобной морали — заходит отлично.\n" +
      "Трилогия закончена: три книги, все переведены на русский. Начинать нужно строго с «Неночи».\n" +
      "Финальная фраза — это моя формулировка того, чем книга отличается от жанровых соседей. На ней и заканчиваем: вопросы?"
    );
  }

  await pres.writeFile({ fileName: "nenoch.pptx" });
  console.log("готово: nenoch.pptx");
}

build().catch((e) => { console.error(e); process.exit(1); });
