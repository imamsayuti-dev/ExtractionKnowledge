# Flask Ekstraksi Pengetahuan NLP

Aplikasi Flask untuk mengklasifikasikan kalimat berbahasa Indonesia berdasarkan kata kunci, menyimpan hasil di MySQL, dan menampilkan tabel serta visualisasi jumlah hasil per kategori.

## Instalasi

Gunakan Python 3.11 atau lebih baru dan MySQL yang masih mendapat dukungan keamanan.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
```

Salin contoh konfigurasi, isi nilainya, lalu ekspor ke environment:

```sh
cp .env.example .env
# Edit .env terlebih dahulu. Jangan commit file ini.
set -a
source .env
set +a
```

`.env` tidak dimuat otomatis. Aplikasi membaca `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, dan `DB_NAME`. `DB_SOCKET` opsional untuk koneksi melalui Unix socket lokal.

Buat database `uas_km` berkarakter `utf8mb4` dan akun database melalui administrator MySQL. Jalankan inisialisasi memakai akun yang memiliki izin CREATE pada database tersebut:

```sh
python setup_database.py
```

Script hanya membuat tabel pada database yang sudah ada. Akun aplikasi saat runtime cukup diberi izin SELECT, INSERT, dan DELETE pada tabel `extracted_knowledge`; CREATE/DROP tidak diperlukan. Skema lama dengan maupun tanpa kolom `id` tetap dapat dibaca tanpa menghapus data. Untuk transaksi yang dapat di-rollback, tabel lama harus menggunakan InnoDB; periksa dan migrasikan melalui administrator setelah backup.

```sh
python app.py
```

Buka `http://127.0.0.1:5000`. Server pengembangan hanya mendengarkan loopback dan debugger dimatikan. Koneksi database baru dibuka saat diperlukan; halaman utama tetap tersedia ketika MySQL sedang tidak tersedia.

## Akses dan konfigurasi keamanan

- Tanpa `APP_PASSWORD`, akses hanya diizinkan dari loopback dan reset dinonaktifkan.
- Dengan `APP_PASSWORD`, seluruh aplikasi memakai HTTP Basic Authentication. Username default `admin`, dapat diubah melalui `APP_USERNAME`. Semua pengguna yang memiliki kredensial ini dapat melihat, menambah, dan menghapus seluruh data; aplikasi tidak memisahkan data per pengguna.
- Sebelum memasang reverse proxy atau membuka akses jaringan, wajib atur `APP_PASSWORD` yang kuat dan `SECRET_KEY` acak yang persisten. Jangan mengandalkan pemeriksaan loopback di belakang proxy. Contoh pembangkitan secret: `python -c 'import secrets; print(secrets.token_hex(32))'`.
- Gunakan server WSGI produksi dan HTTPS untuk akses jaringan. Aktifkan `COOKIE_SECURE=1`, isi `TRUSTED_HOSTS` dengan hostname aplikasi (dipisahkan koma), dan tambahkan pembatasan laju permintaan pada proxy. Basic Authentication harus dilindungi HTTPS. Aplikasi tidak memercayai header proxy secara otomatis.
- `SECRET_KEY` yang kosong menghasilkan secret sementara yang berubah saat restart. Untuk beberapa worker, semua worker harus memakai secret yang sama.
- Semua formulir POST memerlukan token CSRF dari sesi browser. Cookie memakai HttpOnly dan SameSite=Strict. CSP membatasi sumber daya ke origin aplikasi dan melarang skrip inline, embedding, serta plugin objek.
- Kredensial database yang sebelumnya ada di riwayat Git perlu dirotasi pada server database jika pernah digunakan. Menghapusnya dari kode tidak membatalkan kredensial lama.

## Fungsionalitas

- `/`: formulir input, maksimal 10.000 karakter dan 100 kalimat per permintaan; ukuran request maksimal 128 KiB.
- `/result`: ekstraksi melalui POST, serta tabel hasil dengan filter kategori dan pagination 10 baris per halaman melalui GET. Filter diterapkan sebelum pagination.
- `/visual`: grafik batang HTML berdasarkan agregasi database, dengan filter kategori dan jumlah dalam teks. Tidak membutuhkan pustaka grafik JavaScript.
- `/reset`: POST terautentikasi dengan token CSRF untuk menghapus isi tabel dalam transaksi. Struktur tabel tetap tersedia.

Kata kunci disimpan dalam `static/data/keyword_map.txt` dengan format `kategori: kata, frasa kata`. Teks dan kata kunci dinormalisasi dengan stemmer yang sama. Frasa dicocokkan sebagai urutan kata bersebelahan. Kategori dengan jumlah kecocokan unik terbanyak dipilih; jika seri, urutan kategori pada file menentukan hasil. Tidak ada kecocokan menghasilkan `unknown`.

**Cakupan kata kunci** adalah jumlah kata kunci unik yang cocok dibagi jumlah kata kunci unik kategori setelah normalisasi. Skor berada pada rentang 0–100%, bukan ukuran akurasi model. Tokenisasi kalimat memakai aturan Punkt tanpa model terlatih atau unduhan korpus NLTK; singkatan dan konteks bahasa dapat menghasilkan segmentasi yang kurang tepat. Hasil klasifikasi tetap berbasis heuristik kata kunci.

## Pengujian dan audit

```sh
python -m unittest discover -s tests -v
python -m pip install pip-audit
pip-audit
```

Uji integrasi memerlukan **database khusus pengujian** dengan nama berakhiran `_test`. Pengujian membuat ulang tabel `extracted_knowledge` di database tersebut. Jangan gunakan database berisi data penting.

```sh
TEST_MYSQL=1 DB_NAME=extractionknowledge_audit_test \
  python -m unittest discover -s tests -v
```

`requirements.lock` mengunci versi runtime yang diuji. Setelah memperbarui dependensi, perbarui lock, jalankan pengujian, dan pindai ulang. Laporan temuan serta validasi tersedia di [AUDIT.md](AUDIT.md).

## Kredit

Dikembangkan oleh [Bukan Makmum](https://github.com/BukanMakmum), Imam Sayuti dan Yandri Zaita, sebagai proyek mata kuliah Knowledge Management.
