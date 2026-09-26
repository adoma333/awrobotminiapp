// مقاسات الشاشات (نقاط CSS) لأشهر الأجهزة — المعاينة تعرض التطبيق الحقيقي بهذه الأبعاد
export const DEVICES = [
  { id: "iphone_se", group: "iPhone", name: "iPhone SE (3rd gen)", w: 375, h: 667, cut: "none", r: 18 },
  { id: "iphone_13mini", group: "iPhone", name: "iPhone 13 mini", w: 375, h: 812, cut: "notch", r: 44 },
  { id: "iphone_14", group: "iPhone", name: "iPhone 14 / 13", w: 390, h: 844, cut: "notch", r: 47 },
  { id: "iphone_15", group: "iPhone", name: "iPhone 15 / 16", w: 393, h: 852, cut: "island", r: 55 },
  { id: "iphone_16pro", group: "iPhone", name: "iPhone 16 Pro", w: 402, h: 874, cut: "island", r: 55 },
  { id: "iphone_15plus", group: "iPhone", name: "iPhone 15 / 16 Plus", w: 430, h: 932, cut: "island", r: 55 },
  { id: "iphone_16promax", group: "iPhone", name: "iPhone 16 Pro Max", w: 440, h: 956, cut: "island", r: 58 },
  { id: "galaxy_a03", group: "Android", name: "Galaxy A03 (صغير)", w: 360, h: 640, cut: "none", r: 14 },
  { id: "galaxy_s24", group: "Android", name: "Samsung Galaxy S24", w: 360, h: 780, cut: "punch", r: 34 },
  { id: "galaxy_s24u", group: "Android", name: "Galaxy S24 Ultra", w: 384, h: 824, cut: "punch", r: 22 },
  { id: "galaxy_a55", group: "Android", name: "Galaxy A55 / A35", w: 384, h: 854, cut: "punch", r: 32 },
  { id: "fold_cover", group: "Android", name: "Galaxy Z Fold (الشاشة الخارجية)", w: 344, h: 882, cut: "punch", r: 26 },
  { id: "fold_open", group: "Android", name: "Galaxy Z Fold (مفتوح)", w: 690, h: 839, cut: "punch", r: 22 },
  { id: "pixel_8", group: "Android", name: "Google Pixel 8", w: 412, h: 915, cut: "punch", r: 38 },
  { id: "pixel_8pro", group: "Android", name: "Google Pixel 8 Pro", w: 448, h: 998, cut: "punch", r: 36 },
  { id: "redmi_note13", group: "Android", name: "Xiaomi Redmi Note 13", w: 393, h: 873, cut: "punch", r: 32 },
  { id: "oneplus_12", group: "Android", name: "OnePlus 12", w: 412, h: 919, cut: "punch", r: 34 },
  { id: "huawei_p60", group: "Android", name: "Huawei P60 Pro", w: 391, h: 867, cut: "punch", r: 30 },
  { id: "ipad_mini", group: "Tablet", name: "iPad mini", w: 744, h: 1133, cut: "none", r: 22 },
  { id: "ipad_air", group: "Tablet", name: "iPad Air", w: 820, h: 1180, cut: "none", r: 22 },
  { id: "tg_desktop", group: "Desktop", name: "Telegram Desktop", w: 480, h: 760, cut: "window", r: 10 },
];
export const DEVICE_GROUPS = ["iPhone", "Android", "Tablet", "Desktop"];
export const byId = (id) => DEVICES.find((d) => d.id === id) || DEVICES[3];
