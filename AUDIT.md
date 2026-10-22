# Audit fungsi dan keamanan

Tanggal: 23 Oktober 2026 (Asia/Jakarta).

Cakupan: kode Flask, akses database, ekstraksi NLP, template, aset JavaScript, konfigurasi, dan dependensi Python. Tidak ada perubahan pada database pengguna atau deployment produksi. Pengujian database memakai instance sementara dengan jaringan dinonaktifkan dan database `extractionknowledge_audit_test`.

## Temuan dan perbaikan

| Prioritas | Temuan awal | Perbaikan |
| --- | --- | --- |
| Tinggi | Username/password database tersimpan di kode dan README | Konfigurasi environment, contoh tanpa secret, `.env` diabaikan Git. Kredensial lama tetap perlu dirotasi di server jika pernah digunakan. |
| Tinggi | Debugger Flask aktif | Debugger dimatikan; server pengembangan hanya bind loopback. |
| Tinggi | Reset dapat dipanggil siapa pun tanpa autentikasi atau CSRF | Basic Authentication saat password dikonfigurasi, akses anonim hanya loopback, reset dinonaktifkan tanpa password, dan semua POST memeriksa token sesi. |
| Tinggi | Reset menjalankan DROP TABLE, membutuhkan izin DDL dan berisiko menghilangkan struktur | DELETE transaksional dengan commit/rollback; akun runtime tidak memerlukan CREATE/DROP. |
| Tinggi | Skema setup memiliki `id`, sedangkan aplikasi mengandalkan posisi `SELECT *` dari skema tanpa `id` | Skema bersama, pemilihan kolom eksplisit, dan pengujian pada kedua skema lama. |
| Sedang | Satu koneksi global lintas request, cursor tidak ditutup, startup gagal ketika DB tidak tersedia | Koneksi per request, penutupan pada teardown, transaksi terkelola, timeout koneksi dan respons 503 generik. Inisialisasi tabel dipindahkan ke CLI. |
| Sedang | Input tidak divalidasi server dan tidak dibatasi ukurannya | Validasi teks wajib, batas 10.000 karakter, 100 kalimat, 128 KiB request serta batas bagian formulir. Cache stemming dibatasi dan kata sangat panjang tidak distem. |
| Sedang | Frasa kata kunci tidak cocok dan stemming input tidak diterapkan ke kamus | Normalisasi seragam, pencocokan frasa berurutan, kategori dengan kecocokan unik terbanyak. |
| Sedang | Kata berulang menaikkan skor hingga lebih dari 100%; skor dinamai akurasi tanpa evaluasi | Hitungan kecocokan unik dibagi kata kunci unik; label menjadi cakupan kata kunci. |
| Sedang | Tokenizer membutuhkan korpus NLTK yang tidak disiapkan | Punkt berbasis aturan dan tokenisasi kata regex, tanpa unduhan korpus pada startup/request. |
| Sedang | Pagination menghitung header sebagai data dan bertabrakan dengan filter; semua baris dibaca ke memori | Filter SQL berparameter sebelum pagination, 10 baris per halaman, hitungan terpisah, penomoran konsisten, header tetap tampil. |
| Sedang | Visualisasi membaca semua kalimat dan memuat pustaka lama/tidak terpakai | Agregasi COUNT/GROUP BY, filter yang tersedia di UI, batang HTML native; Plotly lama, Mermaid, dan chart.js tidak terpakai dihapus. |
| Sedang | Tidak ada CSP/header keamanan; beberapa handler JS merujuk elemen/fungsi yang tidak ada | JS eksternal minimal, tanpa skrip inline, CSP ketat, nosniff, anti-framing, validasi Host, no-store untuk halaman data. |
| Rendah | Path kamus bergantung working directory dan parsing tidak tervalidasi | Path relatif terhadap modul, UTF-8, validasi baris kamus. |
| Rendah | Tidak ada dependency manifest, dokumentasi konfigurasi aman, atau tes regresi | Manifest versi langsung dan lock runtime, `.env.example`, README baru, unit test dan integrasi MySQL. |

Query kategori sebelumnya sudah memakai parameter SQL. Perlindungan ini dipertahankan dan diuji dengan payload injeksi. Jinja tetap memakai autoescaping, dan pengujian memastikan HTML pada kalimat ditampilkan sebagai teks.

## Validasi

- 16 pengujian lulus: autentikasi, Host, pembatasan akses jaringan, CSRF hilang/salah/antar-sesi, input kosong/terlalu besar/terlalu banyak kalimat, NLP, skor, cleanup koneksi/cursor, commit/rollback, error database, kedua skema lama, XSS tersimpan, injeksi filter, pagination, visualisasi, reset, inisialisasi tabel dan rollback MySQL nyata.
- Database sementara memakai MySQL 5.7.24 yang tersedia di mesin. Ini menguji kompatibilitas query; produksi harus memakai versi MySQL yang masih didukung. Tidak dilakukan pengujian pada server produksi.
- `pip check`, kompilasi modul Python, pemeriksaan sintaks `node --check static/js/app.js`, dan `git diff --check` berhasil.
- `pip-audit` pada environment yang memasang versi runtime di `requirements.lock` tidak menemukan kerentanan yang dikenal. Temuan awal hanya pada pip 26.1.1 di virtual environment baru; pip lokal telah diperbarui ke 26.2.2. Pemindaian kerentanan bukan jaminan bebas celah yang belum diketahui.
- Verifikasi browser visual belum dapat dilakukan: alat Browser gagal pada inisialisasi karena metadata sandbox tidak tersedia (`missing field sandboxPolicy`). Rendering respons HTML dan alur aplikasi diuji melalui Flask test client, termasuk query ke MySQL nyata.

## Batasan dan pengoperasian

Aplikasi memakai satu akun bersama. Seluruh pemegang kredensial dapat menghapus seluruh hasil. Sebelum akses jaringan, operator harus mengatur password dan secret persisten, TLS/HTTPS, secure cookie, trusted hosts, server WSGI produksi dan pembatasan laju pada proxy. Akses loopback tanpa password tidak boleh diteruskan melalui reverse proxy. Nilai environment tidak dimuat otomatis dari `.env`.

Tidak ada klaim akurasi statistik atas ekstraksi. Penentuan kategori memakai kata kunci; tie mengikuti urutan file dan tokenizer berbasis aturan dapat salah memisahkan singkatan. Riwayat hasil lama tidak dihitung ulang. Skema lama tidak diubah otomatis; transaksi memerlukan InnoDB.

Referensi primer: [keamanan Flask](https://flask.palletsprojects.com/en/stable/web-security/) dan [konfigurasi MySQL Connector/Python](https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html).
