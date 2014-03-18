#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <math.h> 

static const int64_t COIN = 100000000;

static const int64_t nDiffChangeTarget = 67200; // Patch effective @ block 67200
static const int64_t patchBlockRewardDuration = 10080; // 10080 blocks main net change

int64_t GetDGBSubsidy(int nHeight) {
   // thanks to RealSolid & WDC for helping out with this code
   int64_t qSubsidy = 8000*COIN;
   int blocks = nHeight - nDiffChangeTarget;
   int weeks = (blocks / patchBlockRewardDuration)+1;
   //decrease reward by 0.5% every week
   for(int i = 0; i < weeks; i++)  qSubsidy -= (qSubsidy/200);  
   return qSubsidy;

}

int64_t static  GetBlockBaseValue(int nHeight) {

   int64_t nSubsidy = COIN;
   
   if(nHeight < nDiffChangeTarget) {
      //this is pre-patch, reward is 8000.
      nSubsidy = 8000 * COIN;
      if(nHeight < 1440)  //1440
      {
        nSubsidy = 72000 * COIN;
      }
      else if(nHeight < 5760)  //5760
      {
        nSubsidy = 16000 * COIN;
      }
      
   } else {
      //patch takes effect after 67,200 blocks solved
      nSubsidy = GetDGBSubsidy(nHeight);
   }

   //make sure the reward is at least 1 DGB
   if(nSubsidy < COIN) {
      nSubsidy = COIN;
   }

   return nSubsidy;
}


#include <boost/python/module.hpp>
#include <boost/python/def.hpp>
using namespace boost::python;
 
BOOST_PYTHON_MODULE(digibyte_subsidy)
{
    def("GetBlockBaseValue", GetBlockBaseValue);
}

