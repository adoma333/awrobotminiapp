"""
أداة سطر أوامر لبوابة الدفع (تعمل على السيرفر فقط، وتقرأ GATEWAY_MASTER_KEY من .env):

  python3 gateway_keys.py new-master            توليد مفتاح رئيسي جديد (يوضع في .env مرة واحدة ولا يُغيَّر بعدها)
  python3 gateway_keys.py gas                   عناوين خزان الغاز للشحن
  python3 gateway_keys.py address tron 123456   عنوان إيداع مستخدم
  python3 gateway_keys.py export tron 123456    المفتاح الخاص لعنوان (لاستيراده في محفظة عند الطوارئ)
  python3 gateway_keys.py export tron gas       المفتاح الخاص لخزان الغاز

المفتاح الخاص يُطبع على الشاشة فقط ولا يُحفظ في أي مكان. لا تشاركه مع أحد.
"""
import secrets
import sys

from dotenv import load_dotenv

load_dotenv()

import gateway  # noqa: E402


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "new-master":
        print(f"GATEWAY_MASTER_KEY={secrets.token_hex(32)}")
        print("⚠️ احفظ نسخة منه في مكان آمن خارج السيرفر: بدونه لا يمكن الوصول لأرصدة عناوين الإيداع.")
        return 0
    if not gateway.master():
        print("GATEWAY_MASTER_KEY غير مضبوط في .env (hex بطول 64 حرفًا على الأقل).")
        return 1
    if cmd == "gas":
        for net in ("tron", "bsc"):
            print(f"{net.upper()}: {gateway.address_of(net, gateway.gas_key(net))}")
        return 0
    if cmd in ("address", "export") and len(argv) == 3 and argv[1] in ("tron", "bsc"):
        net, who = argv[1], argv[2]
        priv = gateway.gas_key(net) if who == "gas" else gateway.deposit_key(net, who)
        print(f"address: {gateway.address_of(net, priv)}")
        if cmd == "export":
            print(f"private key (hex): {priv.hex()}")
            print("⚠️ استورده في TronLink / MetaMask للطوارئ فقط، ثم أغلق الشاشة.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
