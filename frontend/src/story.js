import QRCode from 'qrcode';
import logo from './assets/logo-wordmark.png';
import boy from './assets/icons/boy.webp';
import girl from './assets/icons/girl.webp';

// بطاقة قصة عمودية 9:16 (1080×1920) تُولَّد على الجهاز من بيانات المستخدم الحالية
const W = 1080;
const H = 1920;
const FONT = '"IBM Plex Sans Arabic", system-ui, sans-serif';
const DISPLAY = '"Chakra Petch", "IBM Plex Sans Arabic", system-ui, sans-serif';

const loadImg = (src) =>
  new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/**
 * @param s { dir, nickname, avatar, bigValue, bigLabel, stats: [{label, value}], tierImg, tierLabel, code, link, codeLabel, cta }
 * @returns Promise<Blob>
 */
export async function renderStory(s) {
  await Promise.all([
    document.fonts?.load(`700 64px ${FONT}`),
    document.fonts?.load(`700 64px ${DISPLAY}`),
  ]).catch(() => {});
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const ctx = c.getContext('2d');
  ctx.direction = s.dir || 'rtl';
  ctx.textAlign = 'center';

  // خلفية: أسود + توهج برتقالي + شبكة نقاط
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  const glow = ctx.createRadialGradient(W / 2, 760, 40, W / 2, 760, 900);
  glow.addColorStop(0, 'rgba(255,106,0,0.38)');
  glow.addColorStop(1, 'rgba(255,106,0,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(255,255,255,0.05)';
  for (let x = 30; x < W; x += 54) for (let y = 30; y < H; y += 54) ctx.fillRect(x, y, 3, 3);

  const [lg, av, tier] = await Promise.all([
    loadImg(logo),
    loadImg(s.photo || (s.avatar === 'girl' ? girl : boy)).catch(() => loadImg(s.avatar === 'girl' ? girl : boy)),
    s.tierImg ? loadImg(s.tierImg) : null,
  ]);

  // الشعار
  const lw = 560;
  const lh = (lg.height / lg.width) * lw;
  ctx.drawImage(lg, (W - lw) / 2, 150 - lh / 2 + 20, lw, lh);

  // الصورة والاسم
  ctx.save();
  ctx.beginPath();
  ctx.arc(W / 2, 430, 110, 0, Math.PI * 2);
  ctx.clip();
  const sc = Math.max(220 / av.width, 220 / av.height);
  ctx.drawImage(av, W / 2 - (av.width * sc) / 2, 320, av.width * sc, av.height * sc);
  ctx.restore();
  ctx.lineWidth = 8;
  ctx.strokeStyle = '#ff8a00';
  ctx.beginPath();
  ctx.arc(W / 2, 430, 112, 0, Math.PI * 2);
  ctx.stroke();

  ctx.fillStyle = '#f5efe8';
  ctx.font = `700 64px ${FONT}`;
  ctx.fillText(s.nickname || 'AW Trader', W / 2, 620);

  // الرقم الكبير
  ctx.font = `700 190px ${DISPLAY}`;
  const g = ctx.createLinearGradient(0, 700, 0, 900);
  g.addColorStop(0, '#ffb35c');
  g.addColorStop(1, '#ff5a00');
  ctx.fillStyle = g;
  ctx.direction = 'ltr';
  ctx.fillText(s.bigValue, W / 2, 870);
  ctx.direction = s.dir || 'rtl';
  ctx.fillStyle = '#8c8378';
  ctx.font = `600 44px ${FONT}`;
  ctx.fillText(s.bigLabel, W / 2, 945);

  // ثلاث بطاقات إحصاء
  const stats = (s.stats || []).slice(0, 3);
  const cw = 300;
  const gap = 30;
  const x0 = (W - (cw * stats.length + gap * (stats.length - 1))) / 2;
  stats.forEach((st, i) => {
    const x = x0 + i * (cw + gap);
    roundRect(ctx, x, 1010, cw, 190, 28);
    ctx.fillStyle = 'rgba(255,138,0,0.08)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,138,0,0.35)';
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.fillStyle = '#f5efe8';
    ctx.font = `700 66px ${DISPLAY}`;
    ctx.direction = 'ltr';
    ctx.fillText(st.value, x + cw / 2, 1100);
    ctx.direction = s.dir || 'rtl';
    ctx.fillStyle = '#8c8378';
    let size = 34; // يصغر الخط حتى يتسع النص داخل البطاقة
    do {
      ctx.font = `600 ${size}px ${FONT}`;
      size -= 2;
    } while (ctx.measureText(st.label).width > cw - 32 && size > 20);
    ctx.fillText(st.label, x + cw / 2, 1160);
  });

  // المستوى: الشارة + اسمها في المنتصف تمامًا (الشارة يمين النص في العربية)
  if (tier) {
    ctx.font = `700 46px ${FONT}`;
    const tw = ctx.measureText(s.tierLabel).width;
    const left = (W - (90 + 22 + tw)) / 2;
    const rtl = (s.dir || 'rtl') === 'rtl';
    ctx.drawImage(tier, rtl ? left + tw + 22 : left, 1262, 90, 90);
    ctx.fillStyle = '#f5efe8';
    ctx.textAlign = 'left';
    ctx.fillText(s.tierLabel, rtl ? left : left + 112, 1322);
    ctx.textAlign = 'center';
  }

  // رمز QR + كود الدعوة
  const qr = document.createElement('canvas');
  await QRCode.toCanvas(qr, s.link || s.code, { width: 300, margin: 1, color: { dark: '#000000', light: '#ffffff' } });
  roundRect(ctx, W / 2 - 170, 1370, 340, 340, 30);
  ctx.fillStyle = '#fff';
  ctx.fill();
  ctx.drawImage(qr, W / 2 - 150, 1390, 300, 300);

  ctx.fillStyle = '#8c8378';
  ctx.font = `600 38px ${FONT}`;
  ctx.fillText(s.codeLabel, W / 2, 1752);
  ctx.fillStyle = '#ff8a00';
  ctx.font = `700 58px ${DISPLAY}`;
  ctx.direction = 'ltr';
  ctx.fillText(s.code, W / 2, 1810);
  // الرابط مطبوع على الصورة نفسها (القصة تُنشر بلا نص)
  if (s.link) {
    const short = s.link.replace(/^https?:\/\//, '');
    ctx.font = `600 34px ${DISPLAY}`;
    const tw = ctx.measureText(short).width + 56;
    roundRect(ctx, (W - tw) / 2, 1838, tw, 52, 26);
    ctx.fillStyle = 'rgba(255,138,0,0.14)';
    ctx.fill();
    ctx.fillStyle = '#f5efe8';
    ctx.fillText(short, W / 2, 1875);
  }

  return new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', 0.9));
}

/** منشور مربّع 1080×1080 للمنصات (فيسبوك/إنستغرام/X) ولمعاينة الروابط. */
export async function renderPost(s) {
  await document.fonts?.load(`700 64px ${FONT}`).catch(() => {});
  const S = 1080;
  const c = document.createElement('canvas');
  c.width = S;
  c.height = S;
  const ctx = c.getContext('2d');
  const dir = s.dir || 'rtl';
  ctx.direction = dir;
  ctx.textAlign = 'center';
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, S, S);
  const glow = ctx.createRadialGradient(S / 2, 470, 30, S / 2, 470, 640);
  glow.addColorStop(0, 'rgba(255,106,0,0.36)');
  glow.addColorStop(1, 'rgba(255,106,0,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, S, S);
  ctx.fillStyle = 'rgba(255,255,255,0.05)';
  for (let x = 30; x < S; x += 54) for (let y = 30; y < S; y += 54) ctx.fillRect(x, y, 3, 3);

  const [lg, av] = await Promise.all([loadImg(logo), loadImg(s.photo || (s.avatar === 'girl' ? girl : boy)).catch(() => loadImg(s.avatar === 'girl' ? girl : boy))]);
  const lw = 460;
  ctx.drawImage(lg, (S - lw) / 2, 70, lw, (lg.height / lg.width) * lw);

  ctx.save();
  ctx.beginPath();
  ctx.arc(S / 2, 300, 72, 0, Math.PI * 2);
  ctx.clip();
  const sc = Math.max(144 / av.width, 144 / av.height);
  ctx.drawImage(av, S / 2 - (av.width * sc) / 2, 228, av.width * sc, av.height * sc);
  ctx.restore();
  ctx.strokeStyle = '#ff8a00';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.arc(S / 2, 300, 74, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = '#f5efe8';
  ctx.font = `700 50px ${FONT}`;
  ctx.fillText(s.nickname || 'AW Trader', S / 2, 430);

  const g = ctx.createLinearGradient(0, 480, 0, 640);
  g.addColorStop(0, '#ffb35c');
  g.addColorStop(1, '#ff5a00');
  ctx.fillStyle = g;
  ctx.font = `700 150px ${DISPLAY}`;
  ctx.direction = 'ltr';
  ctx.fillText(s.bigValue, S / 2, 615);
  ctx.direction = dir;
  ctx.fillStyle = '#8c8378';
  ctx.font = `600 38px ${FONT}`;
  ctx.fillText(s.bigLabel, S / 2, 680);

  const stats = (s.stats || []).slice(0, 3);
  const cw = 290;
  const gap = 24;
  const x0 = (S - (cw * stats.length + gap * (stats.length - 1))) / 2;
  stats.forEach((st, i) => {
    const x = x0 + i * (cw + gap);
    roundRect(ctx, x, 730, cw, 150, 24);
    ctx.fillStyle = 'rgba(255,138,0,0.08)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,138,0,0.35)';
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.fillStyle = '#f5efe8';
    ctx.font = `700 54px ${DISPLAY}`;
    ctx.direction = 'ltr';
    ctx.fillText(st.value, x + cw / 2, 805);
    ctx.direction = dir;
    ctx.fillStyle = '#8c8378';
    let size = 30;
    do {
      ctx.font = `600 ${size}px ${FONT}`;
      size -= 2;
    } while (ctx.measureText(st.label).width > cw - 28 && size > 18);
    ctx.fillText(st.label, x + cw / 2, 852);
  });

  ctx.fillStyle = '#8c8378';
  ctx.font = `600 32px ${FONT}`;
  ctx.fillText(s.codeLabel, S / 2, 945);
  ctx.fillStyle = '#ff8a00';
  ctx.font = `700 60px ${DISPLAY}`;
  ctx.direction = 'ltr';
  ctx.fillText(s.code, S / 2, 1015);
  return new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', 0.9));
}
