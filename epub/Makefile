OLD_CHAPTERS := $(sort $(wildcard ../caibidlí/old-orthography/manannan[0-9][0-9].md))
NEW_CHAPTERS := $(sort $(wildcard ../caibidlí/new-orthography/manannan[0-9][0-9].md))
FONTS := $(wildcard fonts/*.otf fonts/*.ttf)

.PHONY: all kindle clean

all: Manannán-Traditional.epub Manannán-Romanised.epub

kindle: Manannán-Traditional-Kindle.epub

Manannán-Traditional.epub: build_epub.py epub.css ../assets/manannan.jpg $(OLD_CHAPTERS) $(FONTS)
	python3 build_epub.py --edition traditional

Manannán-Traditional-Kindle.epub: build_epub.py epub.css ../assets/manannan.jpg $(OLD_CHAPTERS) $(FONTS)
	python3 build_epub.py --edition traditional --insular-rs --out Manannán-Traditional-Kindle.epub

Manannán-Romanised.epub: build_epub.py epub.css ../assets/manannan.jpg $(NEW_CHAPTERS)
	python3 build_epub.py --edition romanised

clean:
	rm -f Manannán-*.epub
