#!/bin/bash

# This script prepares the phoneme-based lexicon. It also generates the list of lexicon units
# and represents the lexicon using the indices of the units. 


srcdir=data/local/train
dir=data
mkdir -p $dir
srcdict=data/resource/lexicon.txt

[ -f path.sh ] && . ./path.sh

. utils/parse_options.sh 



mkdir -p $dir/local/dict_phn
mkdir -p $dir/local/dict



[ ! -f "$srcdict" ] && echo "No such file $srcdict" && exit 1;

cat $srcdict | grep -v "<s>" | grep -v "</s>" | grep -v "!SIL" | LANG= LC_ALL= sort | sed 's:([0-9])::g' > $dir/local/dict_phn/lexicon_words.txt 

# Raw dictionary preparation
cat $dir/local/dict_phn/lexicon_words.txt | \
  perl -e 'while(<>){@A = split; if(! $seen{$A[0]}) {$seen{$A[0]} = 1; print $_;}}' \
  > $dir/local/dict_phn/lexicon.txt || exit 1;


# Get the set of lexicon units without noises
cut -d' ' -f2- $dir/local/dict_phn/lexicon_words.txt | tr ' ' '\n' | sort -u  | awk '{if(NF>0){print $1 " " NR}}' > $dir/local/dict_phn/units_nosil_tmp.txt

#awk '{$1=""; print $0}'  $dir/local/dict_phn/lexicon_words.txt | tr ' ' '\n' | sort -u  | awk '{if(NF>0){print $1 " " NR}}' > $dir/local/dict_phn/units_nosil_tmp.txt

sed '/^$/d' $dir/local/dict_phn/units_nosil_tmp.txt > $dir/local/dict_phn/units_nosil.txt

cat $dir/local/dict_phn/lexicon_words.txt | sort | uniq > $dir/local/dict_phn/lexicon.txt

cat  $dir/local/dict_phn/units_nosil.txt | awk '{print $1 " " NR}' > $dir/local/dict_phn/units.txt
# Convert phoneme sequences into the corresponding sequences of units indices, encoded by units.txt
utils/sym2int.pl -f 2- $dir/local/dict_phn/units.txt < $dir/local/dict_phn/lexicon.txt > $dir/local/dict_phn/lexicon_numbers.txt

echo "Phoneme-based dictionary preparation succeeded"
