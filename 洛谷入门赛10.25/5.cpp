#include <bits/stdc++.h>
using namespace std;
long long n,cnt;
int l=0,r=0,len=3;
int main() {
    cin>>n;
    for(int i=1;i<=n;i++){
        int a;
        cin>>a;
        int add=0;
        if(a==l)add+=2;
        if(l==r)add++;
        l=a;
        r=a;
        cnt=2*cnt+add;
    }
    cout<<cnt<<endl;
}
