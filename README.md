# CSV Cleaner

CSV Cleaner to lokalna aplikacja desktopowa do analizy, czyszczenia i standaryzowania plików CSV oraz XLSX. Dane pozostają na komputerze użytkownika, a plik źródłowy jest chroniony przed przypadkowym nadpisaniem.

## Najważniejsze możliwości

* automatyczne wykrywanie kodowania i separatora CSV
* wybór pliku przez okno systemowe albo przeciągnięcie go do aplikacji
* wybór arkusza w skoroszycie XLSX
* podgląd pierwszych 100 rekordów
* wykrywanie pustych wierszy i kolumn, duplikatów, braków oraz zbędnych odstępów
* wykrywanie potencjalnych kolumn dat i adresów poczty
* czyszczenie odstępów i standaryzowanie nazw kolumn
* usuwanie duplikatów według wszystkich albo wybranych kolumn
* uzupełnianie braków tekstem, zerem, średnią, medianą albo dominantą
* standaryzowanie dat i wielkości liter
* podgląd maksymalnie 500 przykładowych zmian
* bezpieczny zapis CSV lub XLSX przez plik tymczasowy
* raport TXT i JSON tworzony przy każdym zapisie
* lokalny dziennik błędów w katalogu `.csv_cleaner` użytkownika

## Wymagania

* Python 3.11 lub nowszy
* Tkinter dostępny w instalacji Pythona

## Pobieranie gotowej aplikacji na macOS

1. Otwórz stronę repozytorium na GitHub.
2. Przejdź do sekcji **Releases** po prawej stronie.
3. Pobierz plik odpowiedni dla swojego komputera:

| Procesor komputera | Plik |
|---|---|
| Apple Silicon, czyli M1, M2, M3, M4 lub nowszy | `CSV-Cleaner-macOS-arm64.zip` |
| Intel | `CSV-Cleaner-macOS-x86_64.zip` |

4. Otwórz pobrane archiwum ZIP.
5. Przenieś `CSV Cleaner.app` do katalogu `Applications`.
6. Przy pierwszym uruchomieniu kliknij aplikację prawym przyciskiem i wybierz **Otwórz**.

Jeżeli macOS nadal blokuje aplikację, otwórz **Ustawienia systemowe**, następnie **Prywatność i ochrona** i wybierz **Otwórz mimo to**.

Pakiety publikowane automatycznie przez GitHub nie są podpisane certyfikatem Apple. System może więc pokazać ostrzeżenie przy pierwszym uruchomieniu.

## Instalacja i uruchomienie z kodu źródłowego

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

W systemie Windows aktywacja środowiska wygląda następująco:

```powershell
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Uruchomienie

```bash
python run.py
```

Po uruchomieniu wybierz plik CSV albo XLSX przyciskiem lub przeciągnij go do oznaczonego pola. Następnie sprawdź podgląd, rozpocznij analizę, zaznacz operacje, obejrzyj planowane zmiany i zapisz nową kopię.

Przykładowy plik do szybkiego sprawdzenia znajduje się w `sample_data/dirty_sample.csv`.

## Tworzenie aplikacji na macOS po pobraniu kodu

Wymagany jest macOS oraz Python 3.11 lub nowszy. Pobierz kod przez przycisk **Code**, wybierz **Download ZIP** i rozpakuj archiwum. Następnie otwórz Terminal w katalogu projektu i wykonaj:

```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

Skrypt samodzielnie tworzy środowisko, instaluje zależności, buduje aplikację i przygotowuje dwa pliki:

```text
dist/CSV Cleaner.app
dist/CSV-Cleaner-macOS-arm64.zip
```

Końcowa nazwa archiwum zależy od procesora komputera i może kończyć się również na `x86_64.zip`.

## Testy

```bash
python -m pytest
```

Testy zapisano również z użyciem standardowej biblioteki `unittest`, dlatego podstawową weryfikację można wykonać bez instalacji Pytest:

```bash
python -m unittest discover -v
```

## Automatyczne publikowanie przez GitHub

Plik `.github/workflows/build.yml` działa analogicznie do automatyzacji w projekcie Photo Tools. Każdy znacznik wersji zaczynający się literą `v` uruchamia testy i buduje dwa pakiety:

* wersję dla Apple Silicon
* wersję dla komputerów Intel

Po ukończeniu budowania GitHub tworzy wydanie w sekcji **Releases** i dołącza oba archiwa.

Przykład utworzenia wydania:

```bash
git tag v1.1.0
git push origin v1.1.0
```

Automatyzację można również uruchomić ręcznie w karcie **Actions**. Ręczne uruchomienie tworzy pliki w sekcji artefaktów danego zadania, ale nie publikuje nowego wydania.

## Ręczne budowanie przez PyInstaller

Po instalacji zależności uruchom:

```bash
pyinstaller csv_cleaner_macos.spec
```

Gotowy pakiet `CSV Cleaner.app` pojawi się w katalogu `dist`.

## Bezpieczeństwo danych

Aplikacja wykonuje operacje na kopii ramki danych w pamięci. Eksport tworzy najpierw plik tymczasowy i dopiero po poprawnym zapisie zastępuje nim plik docelowy. Nadpisanie istniejącego pliku wymaga potwierdzenia w interfejsie.

## Struktura

Logika odczytu, analizy, czyszczenia, walidacji, eksportu i raportowania znajduje się w `csv_cleaner/core`. Interfejs Tkinter znajduje się w `csv_cleaner/ui`, a modele konfiguracji oraz wyników w `csv_cleaner/models`.
