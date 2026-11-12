OLD_CHAPTERS := $(sort $(wildcard ../caibidlí/old-orthography/manannan[0-9][0-9].md))
NEW_CHAPTERS := $(sort $(wildcard ../caibidlí/new-orthography/manannan[0-9][0-9].md))
FONTS := $(wildcard fonts/*.otf fonts/*.ttf)

.PHONY: all kindle clean

all: Manannán-old.epub Manannán-new.epub

kindle: Manannán-old-kindle.epub

Manannán-old.epub: build_epub.py epub.css ../assets/manannan.jpg $(OLD_CHAPTERS) $(FONTS)
	python3 build_epub.py --edition old

Manannán-old-kindle.epub: build_epub.py epub.css ../assets/manannan.jpg $(OLD_CHAPTERS) $(FONTS)
	python3 build_epub.py --edition old --insular-rs --out Manannán-old-kindle.epub

Manannán-new.epub: build_epub.py epub.css ../assets/manannan.jpg $(NEW_CHAPTERS)
	python3 build_epub.py --edition new

clean:
	rm -f Manannán-old.epub Manannán-old-kindle.epub Manannán-new.epub
