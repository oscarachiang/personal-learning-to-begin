#include <bits/stdc++.h>
using namespace std;
int main() {
   int x, y, z=0,l=0;
   cin>>x>>y;
   for(int i=x;i<=y;i++) {
      string s=to_string(i);
      int k=s.size();
          for(int j=0;j<k;j++){
              if((s[j]%2)!=((j+1)%2))z=1;
          }
      if(z==0){cout<<i<<" ";l=1;}
      z=0;
}
   if(l==0)cout<<"-1";
}
