#include <bits/stdc++.h>
using namespace std;
int n,m;
int a[305],b[305],c[305],d;
int inf=1145141;
int main(){
   cin>>n>>m;
   for(int i=1;i<=n;i++){
     cin>>a[i];
   }
   for(int i=1;i<=m;i++){
     cin>>b[i];
   }
for(int k=1;k<=m;k++){
    if(b[k]!=inf){
        for(int i=1;i<=n;i++){
              for(int j=1;j<=m;j++){
                  if(a[i]>=b[j]){
                      c[i]+=b[j];
                      b[j]=inf;
                      break;
                  }
              }
        }
}
}

   for(int i=1;i<=n;i++){
     cout<<c[i]<<" ";
   }
}
