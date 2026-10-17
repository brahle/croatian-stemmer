MODULE_big = dict_croatian_stem
OBJS = dict_croatian_stem.o croatian_stemmer.o

EXTENSION = dict_croatian_stem
DATA = dict_croatian_stem--1.0.sql
DATA_TSEARCH = croatian.stop

REGRESS = dict_croatian_stem

ifdef USE_PGXS
PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)
else
subdir = contrib/dict_croatian_stem
top_builddir = ../..
include $(top_builddir)/src/Makefile.global
include $(top_srcdir)/contrib/contrib-global.mk
endif
