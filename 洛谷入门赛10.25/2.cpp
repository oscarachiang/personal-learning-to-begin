#include <bits/stdc++.h>
using namespace std;
int main() {
    int n;
    cin >> n;
    for(int i=n; i>0; i--) {
        for(int j=i;j>0; j--) {
            if((n-i)%2==0) cout<<"+";
            else cout<<"-";
        }
        cout<<endl;
    }
}
